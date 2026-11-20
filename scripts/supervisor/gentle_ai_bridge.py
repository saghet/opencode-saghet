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
    r"^\s*(analiza|revisa|audita|diagnostica|explica|investiga|lista|consulta|resume|describe|eval[uú]a\s+sin\s+modificar)\b",
    re.IGNORECASE,
)


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


def classify_and_route(objective: str, context_files: list[str] | None = None) -> dict:
    """
    Capa Gentle AI de clasificación de complejidad, riesgo y enrutamiento de modelos/especialistas.
    Respeta estrictamente la restricción de 8 GB VRAM (OLLAMA_MAX_LOADED_MODELS=1).
    """
    text = (objective or "").strip()
    files = context_files or []
    word_count = len(text.split())
    is_readonly = bool(_READONLY_INTENT_RE.search(text))

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
    }
