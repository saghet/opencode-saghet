#!/usr/bin/env python3
"""
Phase Ledger por proyecto (Fase 3 — Contexto limpio por fase).
Persiste un resumen compacto de handoff en disco para arrancar nuevas fases
en sesiones limpias (< 6k tokens) sin arrastrar 15k-22k tokens de historial.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

DEFAULT_LEDGER_DIR = Path.home() / ".local" / "share" / "opencode-saghet" / "phase_ledgers"


def _project_slug(project_path: str) -> str:
    resolved = str(Path(project_path).resolve()) if project_path and project_path != "*" else "global"
    base = re.sub(r"[^a-zA-Z0-9._-]+", "_", Path(resolved).name or "root").strip("_") or "root"
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:10]
    return f"{base}_{digest}"


def _ledger_file(project_path: str, ledger_dir: Path | None = None) -> Path:
    root = Path(ledger_dir) if ledger_dir else DEFAULT_LEDGER_DIR
    return root / f"{_project_slug(project_path)}.json"


def record_phase_handoff(
    project_path: str,
    phase_name: str,
    summary: str,
    modified_files: list[str] | None = None,
    api_contracts: list[str] | None = None,
    pending_next_step: str = "",
    verifier_status: str = "PENDING",
    ledger_dir: Path | None = None,
) -> dict:
    """Guarda el estado compacto de cierre de fase para continuidad en sesión limpia."""
    target = _ledger_file(project_path, ledger_dir=ledger_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "saghet.phase-ledger/v1",
        "project_path": str(Path(project_path).resolve()) if project_path and project_path != "*" else "*",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "phase_name": str(phase_name).strip(),
        "summary": str(summary).strip()[:600],
        "modified_files": [str(f).strip() for f in (modified_files or []) if str(f).strip()][:20],
        "api_contracts": [str(c).strip() for c in (api_contracts or []) if str(c).strip()][:15],
        "pending_next_step": str(pending_next_step).strip()[:300],
        "verifier_status": str(verifier_status).strip() or "PENDING",
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def get_phase_handoff(
    project_path: str,
    ledger_dir: Path | None = None,
    max_chars: int = 1200,
) -> dict | None:
    """Lee el último handoff de fase del proyecto y genera un bloque compacto para prompt."""
    target = _ledger_file(project_path, ledger_dir=ledger_dir)
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None

    files_str = ", ".join(data.get("modified_files") or []) or "ninguno"
    contracts_str = " | ".join(data.get("api_contracts") or []) or "ninguno"
    compact = (
        f"[PHASE_LEDGER] phase={data.get('phase_name')} | verifier={data.get('verifier_status')}\n"
        f"Resumen: {data.get('summary')}\n"
        f"Archivos: {files_str}\n"
        f"Contratos: {contracts_str}\n"
        f"Siguiente paso: {data.get('pending_next_step') or 'N/A'}"
    )
    if len(compact) > max_chars:
        compact = compact[: max_chars - 3] + "..."
    data["compact_handoff_prompt"] = compact
    return data
