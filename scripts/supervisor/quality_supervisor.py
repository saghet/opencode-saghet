#!/usr/bin/env python3
"""
Supervisor Inteligente de Calidad — OpenCode-Saghet (Fase 2).

Flujo:
1. Gentle AI recibe el objetivo.
2. Clasifica complejidad y riesgo.
3. Selecciona el modelo adecuado respetando 8 GB VRAM.
4. El orquestador distribuye las subtareas (con DAG de dependencias).
5. Los especialistas ejecutan.
6. Un revisor independiente evalúa los cambios.
7. QA ejecuta las pruebas.
8. El supervisor decide ACCEPT, CORRECT (reintento controlado) o REJECT (devolver/rollback).
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from scripts.memory.hierarchical_memory import HierarchicalMemoryStore
from scripts.supervisor.gentle_ai_bridge import classify_and_route, get_gentle_ai_status
from scripts.supervisor.worktree_manager import inspect_worktree

SAGHET_STATE_DIR = Path.home() / ".local" / "share" / "opencode-saghet"
DECISIONS_LEDGER_PATH = SAGHET_STATE_DIR / "supervisor_decisions.jsonl"

# Patrones de detección de errores de razonamiento y falta de evidencia
_PLACEHOLDER_RE = re.compile(
    r"(\bTODO:\s*implement\b|\bNotImplementedError\b|\bpass\s*#\s*placeholder\b|\.\.\.\s*#\s*resto\s+del\s+c[oó]digo)",
    re.IGNORECASE,
)
_UNVERIFIED_CLAIM_RE = re.compile(
    r"(\bno\s+pude\s+ejecutar\s+las\s+pruebas\s+pero\b|\basumo\s+que\s+pasa\b|\bdeber[ií]a\s+funcionar\s+sin\s+probar\b)",
    re.IGNORECASE,
)
_CLAIM_SUCCESS_RE = re.compile(
    r"(\btodas\s+las\s+pruebas\s+pasaron\b|\btests?\s+passed\b|\b0\s+errores\b|\bimplementaci[oó]n\s+exitosa\b|\bAPPROVED\b)",
    re.IGNORECASE,
)
_TEST_FAILURE_RE = re.compile(
    r"(\bFAILED\s*\((?:failures|errors)=|\bAssertionError:|\bTraceback\s+\(most\s+recent\s+call\s+last\):|\bSyntaxError:|\bERROR:\s+test_)",
    re.IGNORECASE,
)
_EVIDENCE_PATH_RE = re.compile(
    r"([a-zA-Z0-9_./-]+\.(?:py|js|ts|json|jsonc|sh|md|toml|html|css|sql)|#[Ll]\d+|\bRan\s+\d+\s+tests?\b|\b\[OK\]\b)",
)

# Taxonomía de 10 clases de error para Self-Debugging Avanzado (Fase 6)
_ERROR_TAXONOMY: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("syntax_error", re.compile(r"\b(SyntaxError|IndentationError|TabError|unexpected\s+token|parse\s+error)\b", re.IGNORECASE)),
    ("compilation_error", re.compile(r"\b(TypeScript|tsc|rustc|gcc|clang|compile\s+error|type\s+error|NameError|AttributeError)\b", re.IGNORECASE)),
    ("dependency_error", re.compile(r"\b(ModuleNotFoundError|ImportError|Cannot\s+find\s+module|ENOENT.*node_modules|pip|npm\s+ERR)\b", re.IGNORECASE)),
    ("permission_error", re.compile(r"\b(PermissionError|EACCES|EROFS|Read-only\s+file\s+system|forbidden|401|403)\b", re.IGNORECASE)),
    ("integration_error", re.compile(r"\b(ConnectionRefusedError|Connection\s+refused|timeout|timed\s+out|JSON-RPC|ACP|HTTP\s+5\d\d)\b", re.IGNORECASE)),
    ("tool_error", re.compile(r"\b(skill_agent_confusion|webfetch_invalid_json_format|edit_oldstring_mismatch|tool\s+error)\b", re.IGNORECASE)),
    ("reasoning_error", re.compile(r"\b(reasoning_contradiction|reasoning_loop|unverified_assumption|incomplete_implementation)\b", re.IGNORECASE)),
    ("architecture_error", re.compile(r"\b(circular\s+import|ciclo\s+detectado|contract\s+mismatch|schema\s+mismatch|architectur)\b", re.IGNORECASE)),
    ("model_error", re.compile(r"\b(empty_or_trivial_response|reasoning_starvation|silent_premature_stop|ollama.*error)\b", re.IGNORECASE)),
    ("git_conflict", re.compile(r"\b(CONFLICT\s*\(|merge conflict|unmerged paths|<<<<<<)\b", re.IGNORECASE)),
    ("edit_mismatch", re.compile(r"\b(oldString not found|edit_oldstring_mismatch|patch does not apply|hunk failed)\b", re.IGNORECASE)),
    ("tool_timeout", re.compile(r"\b(timed out|TimeoutExpired|deadline exceeded|tool_timeout)\b", re.IGNORECASE)),
    ("premature_stop", re.compile(r"\b(silent_premature_stop|empty response|stopped prematurely)\b", re.IGNORECASE)),
    ("functional_error", re.compile(r"\b(AssertionError|FAILED|test_execution_failed|mismatch|expected\s+.*\s+got)\b", re.IGNORECASE)),
)

_SECURITY_DIFF_RE = re.compile(
    r"(\beval\s*\(|\bexec\s*\(|shell\s*=\s*True|\bos\.system\s*\(|sk-[a-zA-Z0-9]{16,}|password\s*=\s*['\"][^'\"]+['\"])",
    re.IGNORECASE,
)


def classify_error(error_text: str, test_returncode: int | None = None) -> str:
    """Clasifica un fallo en una de las 10 categorías de error de ingeniería."""
    combined = (error_text or "").strip()
    for err_class, pat in _ERROR_TAXONOMY:
        if pat.search(combined):
            return err_class
    if test_returncode is not None and test_returncode != 0:
        return "functional_error"
    return "functional_error"


def recommend_recovery_strategy(
    error_class: str,
    iteration: int,
    previous_errors: list[str] | None = None,
) -> str:
    """
    Selecciona estrategia de recuperación y fuerza cambio de enfoque si falla repetidamente.
    """
    prev = previous_errors or []
    repeated = len(prev) >= 2 and prev[-1] == error_class
    if iteration >= 3:
        return "rollback_worktree_and_escalate"
    if repeated or iteration == 2:
        if error_class in {"architecture_error", "integration_error", "dependency_error"}:
            return "inspect_dependencies_and_replan_dag"
        if error_class in {"model_error", "reasoning_error"}:
            return "switch_to_fallback_model_and_narrow_scope"
        return "analyze_root_cause_and_rewrite_patch"
    strategy_by_class = {
        "syntax_error": "fix_syntax_and_reparse",
        "compilation_error": "fix_types_and_imports",
        "dependency_error": "verify_environment_and_imports",
        "permission_error": "use_isolated_worktree_or_ask_permission",
        "integration_error": "check_service_health_and_contract",
        "tool_error": "correct_tool_arguments_and_retry",
        "reasoning_error": "enforce_evidence_and_stepwise_verification",
        "architecture_error": "review_contracts_with_architect",
        "model_error": "retry_with_structured_prompt_or_fallback_model",
        "git_conflict": "abort_or_rebase_clean_worktree",
        "edit_mismatch": "read_target_file_and_apply_atomic_edit",
        "tool_timeout": "split_command_and_increase_timeout_or_abort",
        "premature_stop": "enforce_tool_continuation_and_explicit_verify",
        "functional_error": "debug_failing_assertion_and_patch",
    }
    return strategy_by_class.get(error_class, "debug_failing_assertion_and_patch")


@dataclass
class SubTaskNode:
    task_id: str
    title: str
    specialist: str
    dependencies: list[str] = field(default_factory=list)
    status: str = "PENDING"  # PENDING | READY | RUNNING | COMPLETED | FAILED | BLOCKED
    iterations: int = 0
    max_iterations: int = 3
    verdict: str | None = None
    evidence: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class TaskDependencyDAG:
    """Gestor de dependencias entre subtareas con ordenamiento topológico y propagación de bloqueos."""

    def __init__(self) -> None:
        self.nodes: dict[str, SubTaskNode] = {}

    def add_task(
        self,
        task_id: str,
        title: str,
        specialist: str,
        dependencies: list[str] | None = None,
        max_iterations: int = 3,
    ) -> SubTaskNode:
        node = SubTaskNode(
            task_id=task_id,
            title=title,
            specialist=specialist,
            dependencies=list(dependencies or []),
            max_iterations=max_iterations,
        )
        self.nodes[task_id] = node
        return node

    def validate_acyclic(self) -> tuple[bool, list[str]]:
        """Verifica que no existan ciclos en las dependencias y devuelve el orden topológico."""
        visited: dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=visited
        order: list[str] = []

        def _dfs(nid: str) -> bool:
            state = visited.get(nid, 0)
            if state == 1:
                return False
            if state == 2:
                return True
            visited[nid] = 1
            node = self.nodes.get(nid)
            if node:
                for dep in node.dependencies:
                    if dep not in self.nodes or not _dfs(dep):
                        return False
            visited[nid] = 2
            order.append(nid)
            return True

        for nid in self.nodes:
            if visited.get(nid, 0) == 0:
                if not _dfs(nid):
                    return False, []
        return True, order

    def refresh_states(self) -> dict[str, str]:
        """Actualiza estados a READY o BLOCKED según el resultado de las dependencias."""
        for node in self.nodes.values():
            if node.status in {"COMPLETED", "FAILED", "RUNNING"}:
                continue
            if any(self.nodes[d].status in {"FAILED", "BLOCKED"} for d in node.dependencies if d in self.nodes):
                node.status = "BLOCKED"
            elif all(self.nodes[d].status == "COMPLETED" for d in node.dependencies if d in self.nodes):
                node.status = "READY"
            else:
                node.status = "PENDING"
        return {k: v.status for k, v in self.nodes.items()}

    def get_ready_tasks(self) -> list[SubTaskNode]:
        self.refresh_states()
        return [n for n in self.nodes.values() if n.status == "READY"]

    def replan_after_failure(
        self,
        failed_task_id: str,
        recovery_specialist: str = "senior-developer",
        reason: str = "",
    ) -> dict:
        """Replanifica un nodo fallido creando un nodo de recuperación y redirigiendo dependientes."""
        failed = self.nodes.get(failed_task_id)
        if failed is None:
            return {"ok": False, "error": f"Nodo no encontrado: {failed_task_id}"}

        rec_id = f"{failed_task_id}_recovery"
        if rec_id in self.nodes:
            return {"ok": False, "error": f"Ya existe un nodo de recuperación para {failed_task_id}"}

        self.add_task(
            task_id=rec_id,
            title=f"recovery ({recovery_specialist}): {reason[:80] or failed.title}",
            specialist=recovery_specialist,
            dependencies=list(failed.dependencies),
            max_iterations=2,
        )
        # Re-enlazar nodos que dependían del nodo fallido para que dependan de la recuperación
        relinked: list[str] = []
        for nid, node in self.nodes.items():
            if nid in {failed_task_id, rec_id}:
                continue
            if failed_task_id in node.dependencies:
                node.dependencies = [rec_id if d == failed_task_id else d for d in node.dependencies]
                if node.status == "BLOCKED":
                    node.status = "PENDING"
                relinked.append(nid)
        self.refresh_states()
        return {"ok": True, "recovery_task_id": rec_id, "relinked_tasks": relinked}

    def to_dict(self) -> dict:
        acyclic, order = self.validate_acyclic()
        self.refresh_states()
        return {
            "acyclic": acyclic,
            "topological_order": order,
            "tasks": {
                nid: {
                    "task_id": n.task_id,
                    "title": n.title,
                    "specialist": n.specialist,
                    "dependencies": n.dependencies,
                    "status": n.status,
                    "iterations": n.iterations,
                    "max_iterations": n.max_iterations,
                    "verdict": n.verdict,
                    "errors": n.errors,
                }
                for nid, n in self.nodes.items()
            },
        }


def detect_reasoning_errors(
    agent_output: str,
    test_output: str = "",
    test_returncode: int | None = None,
    reviewer_verdict: str | None = None,
) -> list[str]:
    """
    Detecta errores de razonamiento, contradicciones, bucles repetitivos y código incompleto.
    """
    issues: list[str] = []
    text = (agent_output or "").strip()

    # 1. Contradicción entre afirmación de éxito y fallo real de pruebas
    claims_success = bool(_CLAIM_SUCCESS_RE.search(text))
    tests_failed = (test_returncode is not None and test_returncode != 0) or bool(_TEST_FAILURE_RE.search(test_output or text))
    if claims_success and tests_failed:
        issues.append("reasoning_contradiction: El agente afirma éxito pero la salida de pruebas contiene fallos o returncode != 0.")

    # 2. Placeholders o implementación truncada
    if _PLACEHOLDER_RE.search(text):
        issues.append("incomplete_implementation: Se detectaron placeholders (TODO: implement / NotImplementedError / código truncado).")

    # 3. Afirmaciones sin verificación
    if _UNVERIFIED_CLAIM_RE.search(text):
        issues.append("unverified_assumption: El agente declaró éxito asumiendo resultados sin ejecutar verificación real.")

    # 4. Detección de bucles degenerativos (misma línea no trivial repetida >= 4 veces)
    non_empty_lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 30]
    counts: dict[str, int] = {}
    for ln in non_empty_lines:
        counts[ln] = counts.get(ln, 0) + 1
        if counts[ln] >= 4:
            issues.append("reasoning_loop: Se detectó repetición cíclica (4+ veces) del mismo bloque de salida.")
            break

    # 5. Contradicción con veredicto del revisor independiente
    if reviewer_verdict and reviewer_verdict.upper() == "CHANGES_REQUESTED" and claims_success:
        issues.append("reviewer_conflict: El revisor independiente solicitó cambios (CHANGES_REQUESTED).")

    return issues


def detect_missing_evidence(
    agent_output: str,
    is_readonly: bool,
    diff_files: list[str] | None = None,
    test_returncode: int | None = None,
    require_tests: bool = True,
) -> list[str]:
    """
    Verifica que un agente no declare exitosa una tarea únicamente porque terminó su respuesta.
    """
    missing: list[str] = []
    text = (agent_output or "").strip()

    if not text or len(text) < 20:
        missing.append("empty_or_trivial_response: La respuesta del agente está vacía o carece de contenido técnico.")
        return missing

    if not _EVIDENCE_PATH_RE.search(text):
        missing.append("no_file_or_test_reference: La respuesta no cita rutas de archivos reales, líneas ni resultados de pruebas.")

    if not is_readonly:
        if diff_files is not None and len(diff_files) == 0:
            missing.append("no_code_mutation_detected: La tarea requería cambios pero no se detectaron archivos modificados en el árbol Git.")
        if require_tests and test_returncode is None:
            missing.append("no_test_execution_evidence: No se registró ejecución real de pruebas (test_returncode ausente).")
        elif require_tests and test_returncode != 0:
            missing.append(f"test_execution_failed: Las pruebas finalizaron con código de salida {test_returncode} (!= 0).")

    return missing


def record_decision(decision: dict) -> None:
    """Registra de forma persistente y auditable cada decisión del Supervisor de Calidad."""
    try:
        SAGHET_STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(DECISIONS_LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(decision, ensure_ascii=False) + "\n")
        os.chmod(DECISIONS_LEDGER_PATH, 0o600)
    except Exception:
        pass


def get_decisions(limit: int = 50) -> list[dict]:
    if not DECISIONS_LEDGER_PATH.is_file():
        return []
    try:
        lines = DECISIONS_LEDGER_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        out = []
        for raw in reversed(lines[-limit:]):
            if raw.strip():
                out.append(json.loads(raw))
        return out
    except Exception:
        return []


class QualitySupervisor:
    """
    Sistema Supervisor de Calidad (Fase 2).
    Coordina clasificación Gentle AI, evaluación de evidencia, verificación independiente y reintentos controlados.
    """

    def __init__(self, max_iterations: int = 3) -> None:
        self.max_iterations = max(1, min(5, max_iterations))

    def plan_execution(self, objective: str, directory: Path | None = None, context_files: list[str] | None = None) -> dict:
        """Pasos 1–4: Gentle AI clasifica objetivo, selecciona modelo y construye el DAG adaptativo de subtareas."""
        routing = classify_and_route(
            objective,
            context_files=context_files,
            project_path=str(directory) if directory else "*",
        )
        gentle_status = get_gentle_ai_status(directory)
        repo_context = None
        if directory and Path(directory).is_dir():
            try:
                from scripts.memory.project_intelligence import ProjectIntelligenceEngine
                pi = ProjectIntelligenceEngine()
                pi.index_project(directory)
                repo_context = pi.select_relevant_context(objective, directory, max_chars=1600)
            except Exception:
                repo_context = None
        dag = TaskDependencyDAG()
        reasoning_plan = routing.get("reasoning_plan") or {}

        if not reasoning_plan.get("use_dag", True):
            # Tarea simple/directa: evitar DAG multiagente innecesario
            dag.add_task(
                task_id="step_1_direct",
                title=f"{reasoning_plan.get('strategy', 'direct_response')} ({routing['primary_specialist']})",
                specialist=routing["primary_specialist"],
                dependencies=[],
                max_iterations=1,
            )
        else:
            prev_task_id: str | None = None
            for step in routing["pipeline"]:
                tid = f"step_{step['step']}_{step['agent']}"
                deps = [prev_task_id] if prev_task_id else []
                dag.add_task(
                    task_id=tid,
                    title=f"{step['role']} ({step['agent']})",
                    specialist=step["agent"],
                    dependencies=deps,
                    max_iterations=self.max_iterations,
                )
                prev_task_id = tid

        plan = {
            "plan_id": uuid.uuid4().hex[:12],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "objective_preview": (objective or "")[:200],
            "gentle_ai": gentle_status,
            "routing": routing,
            "reasoning_plan": reasoning_plan,
            "repo_context": repo_context,
            "dag": dag.to_dict(),
        }
        record_decision(
            {
                "decision_id": plan["plan_id"],
                "timestamp": plan["timestamp"],
                "phase": "plan_and_route",
                "verdict": "PLANNED",
                "complexity": routing["complexity"],
                "risk": routing["risk"],
                "strategy": reasoning_plan.get("strategy"),
                "use_dag": reasoning_plan.get("use_dag"),
                "token_budget": reasoning_plan.get("token_budget"),
                "selected_model": routing["selected_model"],
                "primary_specialist": routing["primary_specialist"],
                "worktree_required": routing["worktree_required"],
            }
        )
        return plan

    def evaluate_execution(
        self,
        objective: str,
        agent: str,
        agent_output: str,
        iteration: int = 1,
        is_readonly: bool | None = None,
        worktree_path: Path | None = None,
        diff_files: list[str] | None = None,
        test_output: str = "",
        test_returncode: int | None = None,
        reviewer_verdict: str | None = None,
        require_tests: bool | None = None,
    ) -> dict:
        """
        Pasos 6–8: Evalúa la entrega con verificación independiente, detección de errores de razonamiento
        y detección de resultados sin evidencia.
        Decide: ACCEPT | CORRECT | REJECT.
        """
        routing = classify_and_route(objective)
        ro = routing["is_readonly"] if is_readonly is None else bool(is_readonly)
        req_tests = routing["qa_required"] if require_tests is None else bool(require_tests)

        observed_diffs = diff_files
        if observed_diffs is None and worktree_path and worktree_path.is_dir():
            wt_info = inspect_worktree(worktree_path)
            if wt_info.get("ok"):
                observed_diffs = wt_info.get("changed_files", [])

        reasoning_issues = detect_reasoning_errors(
            agent_output=agent_output,
            test_output=test_output,
            test_returncode=test_returncode,
            reviewer_verdict=reviewer_verdict,
        )
        evidence_issues = detect_missing_evidence(
            agent_output=agent_output,
            is_readonly=ro,
            diff_files=observed_diffs,
            test_returncode=test_returncode,
            require_tests=req_tests,
        )
        if not ro and reviewer_verdict is None:
            evidence_issues.append(
                "missing_independent_review: Toda entrega con cambios de código requiere veredicto independiente (code-reviewer / qa-engineer) antes de ACCEPT."
            )

        all_issues = reasoning_issues + evidence_issues
        can_retry = iteration < self.max_iterations
        error_class = classify_error("\n".join([*all_issues, test_output or "", agent_output or ""]), test_returncode) if all_issues else None
        recovery_strategy = recommend_recovery_strategy(error_class, iteration) if error_class else None

        if not all_issues and ((ro and reviewer_verdict in {None, "APPROVED"}) or (not ro and reviewer_verdict == "APPROVED")):
            verdict = "ACCEPT"
            next_action = "deliver_or_merge"
            correction_prompt = None
        elif can_retry:
            verdict = "CORRECT"
            next_action = f"retry_attempt_{iteration + 1}_of_{self.max_iterations}"
            correction_prompt = (
                f"[SUPERVISOR DE CALIDAD — CORRECCIÓN REQUERIDA (Intento {iteration + 1}/{self.max_iterations})]\n"
                f"Clase de error: {error_class} | Estrategia recomendada: {recovery_strategy}\n"
                f"Tu entrega anterior para '{agent}' fue rechazada por los siguientes defectos verificables:\n"
                + "\n".join(f"- {iss}" for iss in all_issues)
                + "\nCorrige los defectos, ejecuta las pruebas reales y adjunta rutas, diffs y salidas observadas."
            )
        else:
            verdict = "REJECT"
            next_action = "rollback_and_escalate"
            correction_prompt = None

        decision = {
            "decision_id": uuid.uuid4().hex[:12],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "phase": "quality_gate",
            "agent": agent,
            "iteration": iteration,
            "max_iterations": self.max_iterations,
            "is_readonly": ro,
            "verdict": verdict,
            "next_action": next_action,
            "error_class": error_class,
            "recovery_strategy": recovery_strategy,
            "reasoning_errors": reasoning_issues,
            "missing_evidence": evidence_issues,
            "reviewer_verdict": reviewer_verdict or ("APPROVED" if not all_issues else "PENDING"),
            "test_returncode": test_returncode,
            "diff_files_count": len(observed_diffs) if observed_diffs is not None else None,
            "correction_prompt": correction_prompt,
        }
        record_decision(decision)
        try:
            mem_store = HierarchicalMemoryStore()
            if verdict == "ACCEPT":
                cat = "proven_solution" if iteration > 1 else "verified_execution"
                mem_store.store_memory(
                    tier="experience",
                    category=cat,
                    title=f"Ejecución verificada ({agent}): {(objective or '')[:90]}",
                    content=f"Objetivo: {objective}\nAgente: {agent}\nSalida verificada: {(agent_output or '')[:400]}",
                    provenance=f"supervisor:{agent}",
                    context={
                        "agent": agent,
                        "iteration": iteration,
                        "diff_files": observed_diffs or [],
                        "test_returncode": test_returncode,
                        "tags": [agent, cat, *routing.get("domains", [])],
                    },
                    confidence=0.95,
                )
            else:
                err_summary = "; ".join(all_issues)[:400]
                mem_store.store_memory(
                    tier="experience",
                    category="recurring_error",
                    title=f"Defecto detectado en {agent}: {(all_issues[0] if all_issues else 'fallo')[:80]}",
                    content=f"Agente: {agent}\nDefectos detectados: {err_summary}",
                    provenance=f"supervisor:{agent}",
                    context={
                        "agent": agent,
                        "verdict": verdict,
                        "issues": all_issues,
                        "tags": [agent, "recurring_error", *routing.get("domains", [])],
                    },
                    confidence=0.88,
                )
        except Exception:
            pass
        return decision

    def run_independent_review(
        self,
        objective: str,
        acceptance_criteria: list[str] | None = None,
        diff_files: list[str] | None = None,
        diff_text: str = "",
        test_output: str = "",
        test_returncode: int | None = None,
        affected_dependencies: list[str] | None = None,
        reviewer_claim: str = "",
        task_type: str = "general",
    ) -> dict:
        """
        Independent Review 2.0 (Fase 6):
        No acepta un simple 'APPROVED' textual como prueba. Verifica diff real, pruebas ejecutables,
        criterios de aceptación, ausencia de placeholders/riesgos de seguridad y dependencias afectadas.
        """
        findings: list[str] = []
        changed = list(diff_files or [])
        criteria = list(acceptance_criteria or [])
        deps = list(affected_dependencies or [])

        if not changed and not diff_text.strip():
            findings.append("incomplete_solution: No hay archivos modificados ni diff real.")
        if _PLACEHOLDER_RE.search(diff_text):
            findings.append("incomplete_solution: El diff contiene placeholders o código truncado (TODO/NotImplementedError).")
        if _SECURITY_DIFF_RE.search(diff_text):
            findings.append("security_risk: El diff introduce patrones peligrosos (eval/exec/shell=True/os.system/secretos).")
        if test_returncode is None and task_type != "docs":
            findings.append("insufficient_tests: No existe evidencia ejecutable de pruebas (test_returncode ausente).")
        elif test_returncode is not None and (test_returncode != 0 or _TEST_FAILURE_RE.search(test_output)):
            findings.append(f"regression_or_test_failure: Las pruebas fallaron (returncode={test_returncode}).")

        if task_type == "bugfix" and test_returncode != 0:
            findings.append("bugfix_unverified: Un bugfix requiere pruebas ejecutadas con éxito (returncode=0).")
        if task_type == "security" and not any(k in (test_output or "").lower() for k in ("security", "auth", "token", "secret", "ran ", "passed")):
            findings.append("security_unverified: Cambio de seguridad requiere evidencia de pruebas de seguridad o regresión.")

        code_changed = [f for f in changed if f.endswith((".py", ".js", ".ts", ".sh"))]
        if code_changed and not any("test" in f.lower() for f in changed) and "Ran " not in test_output and "PASSED" not in test_output.upper():
            findings.append("insufficient_tests: Se modificó código sin evidencia clara de cobertura de pruebas.")

        # Verificar si algún archivo dependiente crítico quedó sin revisar/probar
        unverified_deps = [d for d in deps if d not in changed and d.endswith((".py", ".ts", ".js"))]
        if unverified_deps and test_returncode != 0:
            findings.append(f"dependency_regression_risk: Dependencias afectadas no validadas ({', '.join(unverified_deps[:4])}).")

        # Verificar contradicción entre criterios de aceptación y diff cuando hay criterios explícitos
        if criteria and diff_text.strip():
            low_diff = (diff_text + " " + " ".join(changed)).lower()
            for crit in criteria:
                key_tokens = [w for w in re.findall(r"[a-zA-Z_]{4,}", crit.lower()) if w not in {"debe", "para", "with", "that", "this"}]
                if key_tokens and not any(tok in low_diff for tok in key_tokens):
                    findings.append(f"criteria_mismatch: El criterio '{crit[:80]}' no tiene respaldo visible en el diff.")

        approved = len(findings) == 0
        return {
            "verdict": "APPROVED" if approved else "CHANGES_REQUESTED",
            "executable_evidence_verified": test_returncode == 0,
            "bare_approval_rejected": (not approved) and ("APPROVED" in (reviewer_claim or "").upper()),
            "findings": findings,
            "diff_files_count": len(changed),
            "affected_dependencies_checked": len(deps),
        }

    def evaluate_transformation_delivery(
        self,
        objective: str,
        output_dir: Path | str,
        equivalence_report: dict,
        reviewer_verdict: str | None = None,
        unrunnable_tests: list[str] | None = None,
    ) -> dict:
        """
        Gate especializado de Validación Funcional y Transformación (Fase 8):
        - Exige evidencia real de la Matriz de Equivalencia Funcional (100% PASS).
        - Ejecuta validador Anti-UI Falsa (`validate_ui_product_integrity`) sobre la interfaz generada.
        - Requiere veredicto independiente (`architecture-validation-specialist` / `code-reviewer`).
        - Declara explícitamente cualquier prueba que no pudo ejecutarse (jamás declara éxito sin evidencia).
        """
        from scripts.intelligence.visual_product import validate_ui_product_integrity

        ui_check = validate_ui_product_integrity(output_dir)
        issues: list[str] = []

        if not ui_check.get("ok"):
            for v in ui_check.get("violations", []):
                issues.append(f"ui_integrity_violation:{v['code']} ({v['file']}): {v['detail']}")

        eq_ok = bool(equivalence_report.get("ok"))
        eq_total = int(equivalence_report.get("total", 0))
        eq_passed = int(equivalence_report.get("passed", 0))
        if eq_total == 0:
            issues.append("missing_equivalence_tests: No se ejecutaron pruebas de equivalencia funcional.")
        elif not eq_ok or eq_passed < eq_total:
            issues.append(f"functional_equivalence_failed: Solo {eq_passed}/{eq_total} funcionalidades pasaron la matriz de equivalencia.")

        unrun = [str(u).strip() for u in (unrunnable_tests or []) if str(u).strip()]
        if reviewer_verdict is None:
            issues.append("missing_independent_review: Falta aprobación independiente de architecture-validation-specialist o code-reviewer.")
        elif reviewer_verdict.upper() != "APPROVED":
            issues.append(f"reviewer_rejected: Veredicto independiente = {reviewer_verdict}.")

        verdict = "ACCEPT" if (not issues and not unrun) else ("CORRECT" if not unrun else "PARTIAL_UNVERIFIED")
        decision = {
            "decision_id": uuid.uuid4().hex[:12],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "phase": "transformation_quality_gate",
            "objective_preview": (objective or "")[:180],
            "verdict": verdict,
            "ui_integrity": ui_check,
            "equivalence_summary": {
                "ok": eq_ok,
                "passed": eq_passed,
                "total": eq_total,
                "equivalence_rate_pct": equivalence_report.get("equivalence_rate_pct", 0.0),
            },
            "unrunnable_tests_declared": unrun,
            "issues": issues,
        }
        record_decision(decision)
        return decision
