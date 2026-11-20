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
        """Pasos 1–4: Gentle AI clasifica objetivo, selecciona modelo y construye el DAG de subtareas."""
        routing = classify_and_route(objective, context_files)
        gentle_status = get_gentle_ai_status(directory)
        dag = TaskDependencyDAG()

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

        all_issues = reasoning_issues + evidence_issues
        can_retry = iteration < self.max_iterations

        if not all_issues and (reviewer_verdict in {None, "APPROVED"}):
            verdict = "ACCEPT"
            next_action = "deliver_or_merge"
            correction_prompt = None
        elif can_retry:
            verdict = "CORRECT"
            next_action = f"retry_attempt_{iteration + 1}_of_{self.max_iterations}"
            correction_prompt = (
                f"[SUPERVISOR DE CALIDAD — CORRECCIÓN REQUERIDA (Intento {iteration + 1}/{self.max_iterations})]\n"
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
