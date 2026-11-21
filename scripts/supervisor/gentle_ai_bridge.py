#!/usr/bin/env python3
"""Puente de integración con Gentle AI (v4.5.0): clasificación, enrutamiento, skills y review ledger."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from scripts.eval.model_lab import SmartModelRouter
from scripts.memory.hierarchical_memory import HierarchicalMemoryStore
from scripts.memory.user_intelligence import UserIntelligenceEngine

GENTLE_AI_BIN = (
    str(Path.home() / ".cargo" / "bin" / "gentle-ai")
    if (Path.home() / ".cargo" / "bin" / "gentle-ai").is_file()
    else (shutil.which("gentle-ai") or "gentle-ai")
)

# Reglas de clasificación de dominio, riesgo y complejidad
_SECURITY_KEYWORDS = re.compile(
    r"\b(seguridad|security|cve|vulnerabilidad|csrf|xss|sql\s*injection|auth|token|secreto|secret|permiso|audit|pentest|rebinding)\b",
    re.IGNORECASE,
)
_ARCH_KEYWORDS = re.compile(
    r"\b(arquitectura|architecture|adr|contrato|contract|diseño\s+modular|migra|refactor\s+global|dag|harness|acp|protocolo)\b",
    re.IGNORECASE,
)
_DB_KEYWORDS = re.compile(
    r"\b(sql|sqlite|postgres|postgresql|redis|valkey|dbhub|esquema|schema|migraci[oó]n|query|explain|tabla)\b",
    re.IGNORECASE,
)
_FRONTEND_KEYWORDS = re.compile(
    r"\b(frontend|ui|ux|css|html|canvas|matrix\s*rain|dashboard\s*ui|componente|tema|theme|accesibilidad|aria)\b",
    re.IGNORECASE,
)
_BACKEND_KEYWORDS = re.compile(
    r"\b(backend|api|endpoint|rest|websocket|servidor|server\.py|concurrencia|proceso|http|handler)\b",
    re.IGNORECASE,
)
_DEVOPS_KEYWORDS = re.compile(
    r"\b(systemd|service|garuda|arch|pacman|docker|worktree|install\.sh|doctor\.sh|update\.sh|ci/cd|deploy)\b",
    re.IGNORECASE,
)
_PERF_KEYWORDS = re.compile(
    r"\b(vram|cuda|gpu|rtx\s*4060|tok/s|ttft|latencia|benchmark|rendimiento|performance|profiling|ram|ollama)\b",
    re.IGNORECASE,
)
_EVAL_KEYWORDS = re.compile(
    r"\b(evaluaci[oó]n\s+de\s+modelo|model\s+eval|first-pass|test\s+pass\s+rate|scoring|laboratorio\s+de\s+modelos)\b",
    re.IGNORECASE,
)
_OBS_KEYWORDS = re.compile(
    r"\b(observabilidad|traza|trace|bucle|loop\s+de\s+razonamiento|session_v2|telemetr[ií]a\s+de\s+agente)\b",
    re.IGNORECASE,
)
_DOC_KEYWORDS = re.compile(
    r"\b(documentaci[oó]n|manual|readme|mermaid|gu[ií]a|changelog)\b",
    re.IGNORECASE,
)
_READONLY_INTENT_RE = re.compile(
    r"^\s*(analiza|revisa|audita|diagnostica|explica|investiga|lista|consulta|resume|describe|"
    r"analyze|review|audit|diagnose|explain|investigate|list|query|summarize|describe|"
    r"eval[uú]a\s+sin\s+modificar)\b",
    re.IGNORECASE,
)

_DEBUG_KEYWORDS = re.compile(
    r"\b(bug|error|fallo|falla|traceback|exception|excepci[oó]n|fix|corrije|corrige|arregla|depura|debug|crash|roto|broken)\b",
    re.IGNORECASE,
)
_COREF_KEYWORDS = re.compile(
    r"\b(como\s+(?:lo\s+)?hablamos|la\s+[uú]ltima\s+vez|anteriormente|lo\s+que\s+ya\s+tenemos|"
    r"no\s+vuelvas\s+a\s+implementar|contin[uú]a|trabajo\s+anterior|sin\s+afectar\s+lo\s+que\s+funciona|"
    r"as\s+we\s+discussed|last\s+time|continue\s+(?:the\s+)?previous|what\s+we\s+(?:already\s+)?have|"
    r"don'?t\s+reimplement|without\s+breaking)\b",
    re.IGNORECASE,
)
_HIGH_IMPACT_KEYWORDS = re.compile(
    r"\b(elimina|borra|delete|drop|truncate|migra|migrate|reescribe\s+todo|rewrite\s+all|"
    r"refactor\s+global|producci[oó]n|production|arquitectura|architecture)\b",
    re.IGNORECASE,
)
_EXPLICIT_CONSTRAINT_RE = re.compile(
    r"\b(sin\s+[\w\s]{2,35}|no\s+uses?\s+[\w\s]{2,25}|mant[eé]n\s+[\w\s]{2,30}|"
    r"compatib[\w]*\s+con\s+[\w\s]{2,25}|without\s+[\w\s]{2,35}|don'?t\s+[\w\s]{2,30}|"
    r"must\s+[\w\s]{2,30}|debe\s+[\w\s]{2,30})\b",
    re.IGNORECASE,
)
_ES_MARKERS = re.compile(r"\b(el|la|los|las|de|que|para|con|sin|haz|mejora|revisa|implementa|corrige|quiero|como|anteriormente)\b", re.IGNORECASE)
_EN_MARKERS = re.compile(r"\b(the|and|for|with|without|fix|implement|review|improve|explain|continue|want|please)\b", re.IGNORECASE)

# Normalización ligera de abreviaturas y errores tipográficos frecuentes
_TYPO_ABBREV_MAP: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(arqui|arq)\b", re.IGNORECASE), "arquitectura"),
    (re.compile(r"\b(bd|bbdd)\b", re.IGNORECASE), "database"),
    (re.compile(r"\b(segur|sec)\b", re.IGNORECASE), "seguridad"),
    (re.compile(r"\b(docu|docs)\b", re.IGNORECASE), "documentacion"),
    (re.compile(r"\b(corrije|arreglar|arrgla)\b", re.IGNORECASE), "corrige"),
    (re.compile(r"\b(implem|impl)\b", re.IGNORECASE), "implementa"),
    (re.compile(r"\b(opt|optimiz)\b", re.IGNORECASE), "optimiza"),
)


def _normalize_multilingual_text(text: str) -> str:
    norm = (text or "").strip()
    for pat, repl in _TYPO_ABBREV_MAP:
        norm = pat.sub(repl, norm)
    return norm


def _detect_language(text: str) -> str:
    es_hits = len(_ES_MARKERS.findall(text or ""))
    en_hits = len(_EN_MARKERS.findall(text or ""))
    if es_hits > 0 and en_hits > 0:
        return "mixed" if abs(es_hits - en_hits) <= 1 else ("es" if es_hits > en_hits else "en")
    if en_hits > es_hits:
        return "en"
    return "es"


class IntentUnderstandingEngine:
    """
    Motor de Comprensión de Intenciones (Fase 1).
    Interpreta instrucciones naturales, informales, multilingües (ES/EN) o con correferencias,
    consulta memoria de usuario/proyecto y decide si actuar o hacer una pregunta de alto valor.
    """

    def __init__(
        self,
        memory_store: HierarchicalMemoryStore | None = None,
        user_engine: UserIntelligenceEngine | None = None,
    ) -> None:
        self._memory_store = memory_store
        self._user_engine = user_engine

    def _get_user_engine(self) -> UserIntelligenceEngine | None:
        if self._user_engine is not None:
            return self._user_engine
        if self._memory_store is not None:
            self._user_engine = UserIntelligenceEngine(self._memory_store)
            return self._user_engine
        try:
            self._memory_store = HierarchicalMemoryStore()
            self._user_engine = UserIntelligenceEngine(self._memory_store)
            return self._user_engine
        except Exception:
            return None

    def interpret(
        self,
        objective: str,
        context_files: list[str] | None = None,
        project_path: str = "*",
    ) -> dict:
        raw_text = (objective or "").strip()
        norm_text = _normalize_multilingual_text(raw_text)
        files = list(context_files or [])
        lang = _detect_language(raw_text)
        has_coref = bool(_COREF_KEYWORDS.search(norm_text))
        is_readonly = bool(_READONLY_INTENT_RE.search(norm_text))
        is_high_impact = bool(_HIGH_IMPACT_KEYWORDS.search(norm_text))

        # Determinar task_type semántico
        if is_readonly:
            task_type = "research"
        elif _DEBUG_KEYWORDS.search(norm_text):
            task_type = "debugging"
        elif _ARCH_KEYWORDS.search(norm_text):
            task_type = "architecture"
        elif norm_text:
            task_type = "coding" if any(
                w in norm_text.lower()
                for w in ("implement", "crea", "añade", "add", "mejora", "improve", "refactor", "optimiza", "corrige", "fix", "test", "script", "api", "endpoint", "función", "function")
            ) or bool(files) else "other"
        else:
            task_type = "other"

        # Extraer restricciones explícitas del enunciado
        explicit_constraints = [m.group(0).strip() for m in _EXPLICIT_CONSTRAINT_RE.finditer(raw_text)][:5]

        # Consultar UserIntelligenceEngine y memoria contextual
        contextual_constraints: list[str] = []
        relevant_memories: list[dict] = []
        user_engine = self._get_user_engine()
        if user_engine is not None:
            try:
                profile = user_engine.get_user_profile(project_path=project_path, query=norm_text)
                for pref in profile.get("active_preferences", []):
                    contextual_constraints.append(f"[{pref.get('key')}] {pref.get('content')}")
                for corr in profile.get("recent_corrections", [])[:2]:
                    contextual_constraints.append(f"[corrección previa] {corr.get('title')}")
                relevant_memories = [
                    {
                        "id": m["id"],
                        "tier": m["tier"],
                        "title": m["title"],
                        "relevance": m["relevance_score"],
                    }
                    for m in profile.get("relevant_memories", [])
                ]
            except Exception:
                pass

        # Detectar capacidades existentes relacionadas en archivos de contexto o proyecto
        existing_capabilities: list[str] = list(files)
        if project_path and project_path != "*" and Path(project_path).is_dir() and not existing_capabilities:
            proj_dir = Path(project_path)
            for candidate_dir in ("scripts", "src", "app", "config"):
                sub = proj_dir / candidate_dir
                if sub.is_dir():
                    existing_capabilities.append(str(sub.relative_to(proj_dir)))

        # Evaluar ambigüedades, confianza y necesidad de pregunta aclaratoria
        ambiguities: list[str] = []
        words = norm_text.split()
        confidence = 0.85

        if not norm_text:
            ambiguities.append("empty_objective")
            confidence = 0.0
        else:
            if len(words) <= 3 and not files:
                ambiguities.append("underspecified_target")
                confidence -= 0.30
            if has_coref and not relevant_memories and not files:
                ambiguities.append("unresolved_coreference_no_memory")
                confidence -= 0.35
            if is_high_impact and len(words) <= 6 and not files:
                ambiguities.append("high_impact_without_scope")
                confidence -= 0.25

        confidence = max(0.0, min(1.0, round(confidence, 2)))

        # Preguntar solo si hay ambigüedad crítica/irreversible o falta total de contexto ejecutable
        requires_clarification = bool(
            (confidence < 0.55 and (is_high_impact or has_coref or task_type == "other"))
            or confidence == 0.0
        )

        clarification_question: str | None = None
        if requires_clarification:
            if "unresolved_coreference_no_memory" in ambiguities:
                clarification_question = (
                    "No encontré en memoria el contexto previo al que te refieres. ¿Qué módulo o archivo específico deseas continuar o modificar?"
                    if lang != "en"
                    else "I could not find the prior context in memory. Which specific module or file would you like me to continue or modify?"
                )
            elif "high_impact_without_scope" in ambiguities:
                clarification_question = (
                    "Esta acción puede tener alto impacto. ¿Sobre qué archivos o componentes exactos debo aplicarla?"
                    if lang != "en"
                    else "This action may have high impact. Which exact files or components should I target?"
                )
            else:
                clarification_question = (
                    "¿Qué objetivo técnico concreto y qué archivos esperas que modifique o analice?"
                    if lang != "en"
                    else "What specific technical outcome and target files should I work on?"
                )

        if requires_clarification:
            recommended_strategy = "ask_single_high_value_clarification"
        elif task_type == "research":
            recommended_strategy = "direct_readonly_investigation"
        elif is_high_impact or task_type == "architecture":
            recommended_strategy = "analyze_dependencies_then_isolated_worktree"
        else:
            recommended_strategy = "execute_focused_implementation_and_verify"

        desired_outcome = (
            "Análisis técnico verificado con rutas y hechos observados"
            if task_type == "research"
            else ("Cambio verificado con pruebas y sin regresiones" if task_type in {"coding", "debugging", "architecture"} else "Respuesta clara acorde al contexto")
        )

        return {
            "user_intent": raw_text[:240],
            "normalized_intent": norm_text[:240],
            "desired_outcome": desired_outcome,
            "task_type": task_type,
            "explicit_constraints": explicit_constraints,
            "contextual_constraints": contextual_constraints[:6],
            "relevant_memories": relevant_memories,
            "existing_capabilities": existing_capabilities[:8],
            "ambiguities": ambiguities,
            "confidence": confidence,
            "recommended_strategy": recommended_strategy,
            "requires_clarification": requires_clarification,
            "clarification_question": clarification_question,
            "detected_language": lang,
            "has_coreference": has_coref,
        }


def get_gentle_ai_status(cwd: Path | None = None) -> dict:
    """Inspecciona el estado real del binario gentle-ai, skills indexadas y review status."""
    bin_path = Path(GENTLE_AI_BIN)
    available = bin_path.is_file() or shutil.which("gentle-ai") is not None
    if not available:
        return {"available": False, "version": None, "skills_count": 0, "review_status": None}

    env = os.environ.copy()
    env["DO_NOT_TRACK"] = "1"
    env["GENTLE_AI_TELEMETRY"] = "0"

    version = None
    try:
        res = subprocess.run([GENTLE_AI_BIN, "--version"], capture_output=True, text=True, timeout=3, env=env, check=False)
        if res.returncode == 0:
            version = res.stdout.strip()
    except Exception:
        pass

    target_cwd = str(cwd or Path.cwd())
    skills = []
    try:
        s_res = subprocess.run(
            [GENTLE_AI_BIN, "skill-registry", "list", "--json", "--cwd", target_cwd],
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
            check=False,
        )
        if s_res.returncode == 0 and s_res.stdout.strip():
            parsed = json.loads(s_res.stdout)
            if isinstance(parsed, list):
                skills = parsed
            elif isinstance(parsed, dict):
                skills = parsed.get("skills") or parsed.get("winners") or []
    except Exception:
        pass

    review_info = None
    try:
        r_res = subprocess.run(
            [GENTLE_AI_BIN, "review", "mode", "status", "--cwd", target_cwd],
            capture_output=True,
            text=True,
            timeout=4,
            env=env,
            check=False,
        )
        if r_res.returncode == 0 and r_res.stdout.strip():
            review_info = r_res.stdout.strip()[:400]
    except Exception:
        pass

    return {
        "available": True,
        "binary": GENTLE_AI_BIN,
        "version": version,
        "skills_discovered": len(skills),
        "review_mode": review_info,
    }


def refresh_gentle_ai_skills(cwd: Path) -> bool:
    """Sincroniza el registro de skills en disco mediante gentle-ai skill-registry refresh."""
    if not (Path(GENTLE_AI_BIN).is_file() or shutil.which("gentle-ai")):
        return False
    env = os.environ.copy()
    env["DO_NOT_TRACK"] = "1"
    env["GENTLE_AI_TELEMETRY"] = "0"
    try:
        res = subprocess.run(
            [GENTLE_AI_BIN, "skill-registry", "refresh", "--quiet", "--no-gitignore", "--cwd", str(cwd)],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            check=False,
        )
        return res.returncode == 0
    except Exception:
        return False


def classify_and_route(
    objective: str,
    context_files: list[str] | None = None,
    project_path: str = "*",
    memory_store: HierarchicalMemoryStore | None = None,
    user_engine: UserIntelligenceEngine | None = None,
) -> dict:
    """
    Capa Gentle AI de clasificación de complejidad, riesgo y enrutamiento de modelos/especialistas.
    Integra `IntentUnderstandingEngine` y respeta la restricción de 8 GB VRAM (OLLAMA_MAX_LOADED_MODELS=1).
    """
    intent_engine = IntentUnderstandingEngine(memory_store=memory_store, user_engine=user_engine)
    intent_analysis = intent_engine.interpret(objective, context_files=context_files, project_path=project_path)

    text = (intent_analysis.get("normalized_intent") or objective or "").strip()
    files = context_files or []
    word_count = len(text.split())
    is_readonly = bool(_READONLY_INTENT_RE.search(text)) or intent_analysis.get("task_type") == "research"

    # Detectar dominios involucrados
    domains: list[str] = []
    if _SECURITY_KEYWORDS.search(text):
        domains.append("security")
    if _ARCH_KEYWORDS.search(text):
        domains.append("architecture")
    if _DB_KEYWORDS.search(text):
        domains.append("database")
    if _FRONTEND_KEYWORDS.search(text):
        domains.append("frontend")
    if _BACKEND_KEYWORDS.search(text):
        domains.append("backend")
    if _DEVOPS_KEYWORDS.search(text):
        domains.append("devops")
    if _PERF_KEYWORDS.search(text):
        domains.append("performance")
    if _EVAL_KEYWORDS.search(text):
        domains.append("evaluation")
    if _OBS_KEYWORDS.search(text):
        domains.append("observability")
    if _DOC_KEYWORDS.search(text):
        domains.append("documentation")
    if not domains:
        domains.append("general")

    # Clasificar riesgo
    if "security" in domains and not is_readonly:
        risk = "security_sensitive"
    elif is_readonly:
        risk = "read_only"
    elif "architecture" in domains or "database" in domains or len(domains) >= 3 or len(files) > 5:
        risk = "architectural"
    else:
        risk = "standard_mutation"

    # Clasificar complejidad
    if is_readonly and word_count <= 25 and len(domains) == 1 and "architecture" not in domains and "security" not in domains:
        complexity = "low"
    elif risk == "security_sensitive" or (len(domains) >= 3 and not is_readonly):
        complexity = "critical"
    elif risk == "architectural" or len(domains) >= 2 or word_count > 80:
        complexity = "high"
    else:
        complexity = "medium"

    # Seleccionar especialista principal, modelo y pipeline de verificación usando SmartModelRouter
    # Regla VRAM RTX 4060 (8 GB): minimizar cambios de modelo innecesarios (qwen3.5:9b residente).
    smart_router = SmartModelRouter()
    if complexity == "low" and is_readonly:
        primary_specialist = "fast-helper"
        route_decision = smart_router.route("classification", avoid_vram_swap=False)
        selected_model = route_decision["selected_model"]
        reviewers = []
        qa_required = False
        worktree_required = False
    else:
        # Mapear dominio a especialista
        domain_to_agent = {
            "security": "platform-security-engineer" if "backend" in domains or "devops" in domains else "security-auditor",
            "architecture": "integration-architect" if ("harness" in text.lower() or "acp" in text.lower() or "mcp" in text.lower()) else "architect",
            "database": "database-specialist",
            "frontend": "frontend-specialist",
            "backend": "backend-specialist",
            "devops": "devops-engineer",
            "performance": "performance-engineer",
            "evaluation": "agent-evaluation-engineer",
            "observability": "agent-observability-engineer",
            "documentation": "documentation-engineer",
            "general": "researcher" if is_readonly else "senior-developer",
        }
        primary_Domain = domains[0]
        if not is_readonly and primary_Domain in {"security", "architecture"}:
            # Si hay mutación pero el dominio detectado es seguridad/arquitectura, el ejecutor debe tener permisos R/W
            if "backend" in domains:
                primary_specialist = "backend-specialist"
            elif "frontend" in domains:
                primary_specialist = "frontend-specialist"
            elif "devops" in domains:
                primary_specialist = "devops-engineer"
            else:
                primary_specialist = "senior-developer"
        else:
            primary_specialist = domain_to_agent.get(primary_Domain, "senior-developer")

        if primary_specialist in {"security-auditor", "platform-security-engineer"}:
            route_decision = smart_router.route("security_audit")
        elif primary_specialist in {"architect", "integration-architect"}:
            route_decision = smart_router.route("architecture")
        elif primary_specialist == "code-reviewer":
            route_decision = smart_router.route("independent_review")
        else:
            route_decision = smart_router.route("coding")
        selected_model = route_decision["selected_model"]

        if is_readonly:
            reviewers = ["code-reviewer"] if complexity in {"high", "critical"} else []
            qa_required = False
            worktree_required = False
        else:
            reviewers = ["code-reviewer"]
            if risk == "security_sensitive" or "security" in domains:
                reviewers.append("security-auditor")
            qa_required = primary_specialist != "documentation-engineer"
            worktree_required = complexity in {"high", "critical"} or risk in {"architectural", "security_sensitive"}

    pipeline_steps = []
    if complexity in {"high", "critical"} and not is_readonly:
        pipeline_steps.append({"step": 1, "agent": "architect", "role": "design_and_contracts", "read_only": True})
    pipeline_steps.append(
        {
            "step": len(pipeline_steps) + 1,
            "agent": primary_specialist,
            "role": "execution",
            "read_only": is_readonly,
        }
    )
    for rev in reviewers:
        pipeline_steps.append(
            {
                "step": len(pipeline_steps) + 1,
                "agent": rev,
                "role": "independent_review",
                "read_only": True,
            }
        )
    if qa_required:
        pipeline_steps.append(
            {
                "step": len(pipeline_steps) + 1,
                "agent": "qa-engineer",
                "role": "qa_verification",
                "read_only": False,
            }
        )

    return {
        "layer": "gentle-ai-4.5.0",
        "complexity": complexity,
        "risk": risk,
        "is_readonly": is_readonly,
        "domains": domains,
        "selected_model": selected_model,
        "fallback_chain": route_decision.get("fallback_chain", []),
        "verifiable_model_score": route_decision.get("verifiable_score"),
        "primary_specialist": primary_specialist,
        "reviewers": reviewers,
        "qa_required": qa_required,
        "worktree_required": worktree_required,
        "max_iterations": 3,
        "max_retries": 2,
        "vram_policy": "sequential_single_model_8gb",
        "pipeline": pipeline_steps,
        "intent_analysis": intent_analysis,
        "reasoning_plan": build_adaptive_reasoning_plan(
            complexity=complexity,
            risk=risk,
            is_readonly=is_readonly,
            domains=domains,
            intent_analysis=intent_analysis,
            pipeline_steps=pipeline_steps,
        ),
    }


def build_adaptive_reasoning_plan(
    complexity: str,
    risk: str,
    is_readonly: bool,
    domains: list[str],
    intent_analysis: dict,
    pipeline_steps: list[dict],
) -> dict:
    """
    Adaptive Reasoning Engine (Fase 4):
    Evalúa complejidad, riesgo, incertidumbre, impacto, reversibilidad y coste para
    elegir la estrategia y presupuesto de tokens proporcional a la tarea.
    """
    confidence = float(intent_analysis.get("confidence", 0.85))
    uncertainty = round(max(0.0, min(1.0, 1.0 - confidence)), 2)
    requires_clarification = bool(intent_analysis.get("requires_clarification", False))
    task_type = intent_analysis.get("task_type", "other")

    if risk == "security_sensitive" or complexity == "critical":
        impact = "high"
        reversibility = "partially_reversible"
    elif risk == "architectural" or complexity == "high":
        impact = "high"
        reversibility = "reversible"
    elif is_readonly:
        impact = "low"
        reversibility = "reversible"
    else:
        impact = "medium"
        reversibility = "reversible"

    if requires_clarification:
        strategy = "clarification"
        use_dag = False
        token_budget = 384
        execution_cost = "low"
    elif complexity == "low" and is_readonly:
        strategy = "direct_response" if task_type == "other" else "research"
        use_dag = False
        token_budget = 768
        execution_cost = "low"
    elif task_type == "debugging":
        strategy = "debugging"
        use_dag = len(pipeline_steps) > 1
        token_budget = 2048 if complexity in {"high", "critical"} else 1536
        execution_cost = "medium"
    elif risk == "architectural" or complexity in {"high", "critical"}:
        strategy = "planning" if is_readonly else "delegation"
        use_dag = True
        token_budget = 3072 if complexity == "critical" else 2560
        execution_cost = "high"
    elif is_readonly:
        strategy = "repo_analysis"
        use_dag = False
        token_budget = 1280
        execution_cost = "low"
    else:
        strategy = "execution"
        use_dag = len(pipeline_steps) > 1
        token_budget = 1792
        execution_cost = "medium"

    rationale = (
        f"Estrategia '{strategy}' para complejidad={complexity}, riesgo={risk}, "
        f"incertidumbre={uncertainty}, impacto={impact}; "
        f"{'DAG multi-etapa' if use_dag else 'ejecución directa sin DAG innecesario'}."
    )

    return {
        "strategy": strategy,
        "complexity": complexity,
        "risk": risk,
        "uncertainty": uncertainty,
        "impact": impact,
        "reversibility": reversibility,
        "execution_cost": execution_cost,
        "token_budget": token_budget,
        "use_dag": use_dag,
        "requires_dependency_analysis": risk in {"architectural", "security_sensitive"} or complexity in {"high", "critical"},
        "decision_rationale": rationale,
    }
