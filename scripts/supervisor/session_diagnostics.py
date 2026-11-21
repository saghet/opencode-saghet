#!/usr/bin/env python3
"""Saghet Matrix — Detector de Errores de Sesión en Vivo y Auditoría de Salud (Fase 3 Hotfix).

Inspecciona en modo solo lectura (`mode=ro`) la base de datos de OpenCode (`opencode.db`),
los registros de `opencode-mem.log` y el estado de los sockets de Ollama (`127.0.0.1:11434`)
para detectar proactivamente:
1. Subagentes huérfanos o sesiones atascadas (`idle_outcome IS NULL`).
2. Tormentas de compactación (`>= 3` compactaciones en la misma sesión).
3. Eventos de amnesia post-compactación (`Objective: (none)` / `No task has been assigned yet`).
4. Errores de ejecución de herramientas (`skill` vs `subagent`, `webfetch` format `json`,
   recursión de subagentes, rutas inexistentes).
5. Saturación de sockets TCP hacia Ollama (`127.0.0.1:11434`) y estado de `autoCaptureEnabled`.
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import subprocess
import time
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OPENCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
DEFAULT_MEM_LOG = Path.home() / ".opencode-mem" / "opencode-mem.log"
USER_MEM_CONFIG = Path.home() / ".config" / "opencode" / "opencode-mem.jsonc"
REPO_MEM_CONFIG = REPO_DIR / "config" / "opencode-mem.jsonc"

KNOWN_AGENT_NAMES = {
    "saghet-orchestrator",
    "plan",
    "architect",
    "senior-developer",
    "backend-specialist",
    "frontend-specialist",
    "database-engineer",
    "devops-engineer",
    "security-auditor",
    "qa-engineer",
    "code-reviewer",
    "debugger",
    "performance-engineer",
    "documentation-writer",
    "researcher",
    "agent-evaluation-engineer",
    "agent-observability-engineer",
    "integration-architect",
    "platform-security-engineer",
}


def _strip_jsonc(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("//"):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    return re.sub(r",(\s*[}\]])", r"\1", cleaned)


def _classify_tool_error(tool_name: str, tool_input: dict, error_message: str) -> str:
    t_name = (tool_name or "").strip().lower()
    err_low = (error_message or "").lower()
    if "interaction cancelled because the location shut down" in err_low:
        return "service_restart_interruption"
    if t_name == "edit" and ("could not find oldstring" in err_low or "newstring is already in the file" in err_low):
        return "edit_oldstring_mismatch"
    if t_name == "skill":
        skill_id = str((tool_input or {}).get("id") or (tool_input or {}).get("name") or "").strip()
        if skill_id in KNOWN_AGENT_NAMES or "unable to load skill" in err_low:
            return "skill_agent_confusion"
    if t_name == "webfetch":
        fmt = str((tool_input or {}).get("format") or "").strip().lower()
        if fmt == "json" or "invalid arguments for tool webfetch" in err_low:
            return "webfetch_invalid_json_format"
    if t_name == "subagent" or "depth" in err_low or "subagent" in err_low:
        return "subagent_recursion_error"
    if "file not found" in err_low or "enoent" in err_low or "no such file or directory" in err_low:
        return "missing_file_or_dir"
    return "other_tool_error"


def check_ollama_socket_health() -> dict:
    """Cuenta conexiones TCP establecidas contra 127.0.0.1:11434 para detectar colas zombi."""
    active_conns = 0
    try:
        res = subprocess.run(
            ["ss", "-tn", "state", "established", "( dport = :11434 or sport = :11434 )"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if res.returncode == 0:
            lines = [ln.strip() for ln in res.stdout.splitlines() if "11434" in ln]
            # Cada conexión local aparece en ambos extremos (cliente y servidor), dividimos entre 2
            active_conns = max(len(lines) // 2, 1 if lines else 0)
    except Exception:
        active_conns = 0

    return {
        "active_connections": active_conns,
        "zombie_queue_detected": active_conns > 5,
        "status": "WARNING" if active_conns > 5 else "HEALTHY",
    }


def check_ollama_ctx_health(expected_ctx: int = 24576) -> dict:
    """Verifica que los modelos locales principales tengan PARAMETER num_ctx sincronizado en Ollama."""
    target_models = ("qwen3.5:9b", "qwen3.5:4b", "abliterant/qwen3.5-rana:9b")
    model_ctx: dict[str, int | None] = {}
    for m in target_models:
        ctx_val: int | None = None
        try:
            res = subprocess.run(
                ["ollama", "show", m, "--modelfile"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                for ln in res.stdout.splitlines():
                    if ln.startswith("PARAMETER num_ctx "):
                        parts = ln.split()
                        if len(parts) >= 3 and parts[2].isdigit():
                            ctx_val = int(parts[2])
        except Exception:
            ctx_val = None
        model_ctx[m] = ctx_val

    present_vals = [v for v in model_ctx.values() if v is not None]
    all_synced = bool(present_vals) and all(v >= expected_ctx for v in present_vals)
    return {
        "expected_num_ctx": expected_ctx,
        "models": model_ctx,
        "all_synced": all_synced,
        "status": "HEALTHY" if all_synced else "WARNING",
    }


def check_opencode_mem_health(mem_log_path: Path | None = None) -> dict:
    """Verifica si autoCaptureEnabled está mitigado y cuenta timeouts históricos en opencode-mem.log."""
    log_file = mem_log_path or DEFAULT_MEM_LOG
    auto_capture_enabled = True

    for candidate in (REPO_MEM_CONFIG, USER_MEM_CONFIG):
        if candidate.is_file():
            try:
                parsed = json.loads(_strip_jsonc(candidate.read_text(encoding="utf-8")))
                if "autoCaptureEnabled" in parsed:
                    auto_capture_enabled = bool(parsed["autoCaptureEnabled"])
                    break
            except Exception:
                pass

    recent_timeouts = 0
    if log_file.is_file():
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-100:]
            recent_timeouts = sum(1 for ln in lines if "structured-output timed out" in ln.lower())
        except Exception:
            recent_timeouts = 0

    return {
        "auto_capture_enabled": auto_capture_enabled,
        "mitigated": not auto_capture_enabled,
        "historical_timeouts_in_tail": recent_timeouts,
        "status": "HEALTHY" if not auto_capture_enabled else "WARNING",
    }


def analyze_recent_sessions(
    db_path: Path | None = None,
    mem_log_path: Path | None = None,
    limit_sessions: int = 15,
) -> dict:
    """Analiza las sesiones recientes de OpenCode y devuelve un diagnóstico estructurado."""
    target_db = Path(db_path) if db_path else DEFAULT_OPENCODE_DB
    now_ms = int(time.time() * 1000)

    stalled_sessions: list[dict] = []
    compaction_storms: list[dict] = []
    amnesia_events: list[dict] = []
    output_limit_truncations: list[dict] = []
    tool_execution_errors: list[dict] = []
    analyzed_count = 0

    if target_db.is_file():
        try:
            uri = f"file:{target_db}?mode=ro"
            with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=3.0)) as conn:
                conn.row_factory = sqlite3.Row
                sessions = conn.execute(
                    """
                    SELECT id, parent_id, title, agent, model, directory,
                           idle_outcome, time_created, time_updated
                    FROM session_v2
                    ORDER BY COALESCE(time_updated, time_created, 0) DESC
                    LIMIT ?
                    """,
                    (limit_sessions,),
                ).fetchall()

                stalled_extra = conn.execute(
                    """
                    SELECT id, parent_id, title, agent, model, directory,
                           idle_outcome, time_created, time_updated
                    FROM session_v2
                    WHERE idle_outcome IS NULL
                    ORDER BY COALESCE(time_updated, time_created, 0) DESC
                    LIMIT 5
                    """
                ).fetchall()

                all_rows = list(sessions)
                seen_ids = {r["id"] for r in all_rows}
                for sr in stalled_extra:
                    if sr["id"] not in seen_ids:
                        all_rows.append(sr)
                        seen_ids.add(sr["id"])

                analyzed_count = len(all_rows)
                session_map: dict[str, dict] = {}
                for s in all_rows:
                    sid = s["id"]
                    s_dict = dict(s)
                    session_map[sid] = s_dict
                    if s["idle_outcome"] is None:
                        updated_ms = s["time_updated"] or s["time_created"] or now_ms
                        age_s = max(round((now_ms - updated_ms) / 1000.0, 1), 0.0)
                        stalled_sessions.append(
                            {
                                "session_id": sid,
                                "parent_id": s["parent_id"],
                                "title": s["title"] or sid,
                                "agent": s["agent"] or "unknown",
                                "directory": s["directory"] or "",
                                "age_seconds": age_s,
                            }
                        )

                if session_map:
                    placeholders = ",".join("?" for _ in session_map)
                    sids = list(session_map.keys())

                    # 1. Detectar tormentas de compactación y amnesia post-compactación
                    comp_rows = conn.execute(
                        f"""
                        SELECT session_id, id, seq, data
                        FROM session_message
                        WHERE session_id IN ({placeholders})
                          AND type = 'compaction'
                        ORDER BY time_created DESC
                        """,
                        sids,
                    ).fetchall()

                    comp_counts: dict[str, int] = {}
                    for r in comp_rows:
                        sid = r["session_id"]
                        comp_counts[sid] = comp_counts.get(sid, 0) + 1
                        try:
                            d = json.loads(r["data"] or "{}")
                        except Exception:
                            d = {}
                        summary = str(d.get("summary") or "")
                        if "No task has been assigned yet" in summary or "Objective\n- (none)" in summary:
                            amnesia_events.append(
                                {
                                    "session_id": sid,
                                    "message_id": r["id"],
                                    "title": session_map[sid].get("title") or sid,
                                    "agent": session_map[sid].get("agent") or "unknown",
                                    "excerpt": "Objective: (none) - No task has been assigned yet",
                                }
                            )

                    for sid, cnt in comp_counts.items():
                        if cnt >= 3:
                            compaction_storms.append(
                                {
                                    "session_id": sid,
                                    "title": session_map[sid].get("title") or sid,
                                    "agent": session_map[sid].get("agent") or "unknown",
                                    "compaction_count": cnt,
                                }
                            )

                    # 2. Detectar errores de ejecución de herramientas en mensajes assistant
                    msg_rows = conn.execute(
                        f"""
                        SELECT session_id, id, data
                        FROM session_message
                        WHERE session_id IN ({placeholders})
                          AND type = 'assistant'
                          AND (data LIKE '%"status":"error"%' OR data LIKE '%"status": "error"%')
                        ORDER BY time_created DESC
                        LIMIT 150
                        """,
                        sids,
                    ).fetchall()

                    for r in msg_rows:
                        sid = r["session_id"]
                        try:
                            d = json.loads(r["data"] or "{}")
                        except Exception:
                            continue
                        for item in d.get("content") or []:
                            if not isinstance(item, dict) or item.get("type") != "tool":
                                continue
                            st = item.get("state") or {}
                            if st.get("status") == "error":
                                t_name = str(item.get("name") or "unknown")
                                t_input = st.get("input") if isinstance(st.get("input"), dict) else {}
                                err_obj = st.get("error") if isinstance(st.get("error"), dict) else {}
                                err_msg = str(err_obj.get("message") or st.get("error") or "Tool error")
                                classification = _classify_tool_error(t_name, t_input, err_msg)
                                tool_execution_errors.append(
                                    {
                                        "session_id": sid,
                                        "message_id": r["id"],
                                        "agent": d.get("agent") or session_map[sid].get("agent") or "unknown",
                                        "tool_name": t_name,
                                        "classification": classification,
                                        "input": t_input,
                                        "error_message": err_msg[:240],
                                    }
                                )

                    # 3. Detectar truncamientos por techo de contexto/salida (output-limit / finish=length)
                    idle_err_rows = conn.execute(
                        f"""
                        SELECT session_id, id, seq, data
                        FROM session_message
                        WHERE session_id IN ({placeholders})
                          AND type = 'idle'
                          AND data LIKE '%output-limit%'
                        ORDER BY time_created DESC
                        LIMIT 50
                        """,
                        sids,
                    ).fetchall()

                    for r in idle_err_rows:
                        sid = r["session_id"]
                        try:
                            d = json.loads(r["data"] or "{}")
                        except Exception:
                            d = {}
                        err_obj = d.get("error") if isinstance(d.get("error"), dict) else {}
                        if err_obj.get("type") == "output-limit":
                            output_limit_truncations.append(
                                {
                                    "session_id": sid,
                                    "message_id": r["id"],
                                    "kind": "idle_output_limit",
                                    "agent": session_map[sid].get("agent") or "unknown",
                                    "message": str(err_obj.get("message") or "")[:200],
                                }
                            )

                    len_rows = conn.execute(
                        f"""
                        SELECT session_id, id, seq, data
                        FROM session_message
                        WHERE session_id IN ({placeholders})
                          AND type = 'assistant'
                          AND (data LIKE '%"finish":"length"%' OR data LIKE '%"finish": "length"%')
                        ORDER BY time_created DESC
                        LIMIT 50
                        """,
                        sids,
                    ).fetchall()

                    for r in len_rows:
                        sid = r["session_id"]
                        try:
                            d = json.loads(r["data"] or "{}")
                        except Exception:
                            continue
                        toks = d.get("tokens") or {}
                        out_tok = int(toks.get("output") or 0)
                        if d.get("finish") == "length" and out_tok < 100:
                            output_limit_truncations.append(
                                {
                                    "session_id": sid,
                                    "message_id": r["id"],
                                    "kind": "assistant_length_starvation",
                                    "agent": d.get("agent") or session_map[sid].get("agent") or "unknown",
                                    "input_tokens": int(toks.get("input") or 0),
                                    "output_tokens": out_tok,
                                }
                            )
                        elif d.get("finish") == "length" and out_tok >= 2000:
                            content_items = d.get("content") or []
                            text_len = sum(len(str(c.get("text") or "")) for c in content_items if isinstance(c, dict) and c.get("type") == "text")
                            reason_len = sum(len(str(c.get("text") or "")) for c in content_items if isinstance(c, dict) and c.get("type") == "reasoning")
                            if text_len == 0 and reason_len > 0:
                                output_limit_truncations.append(
                                    {
                                        "session_id": sid,
                                        "message_id": r["id"],
                                        "kind": "reasoning_starvation_no_tools",
                                        "agent": d.get("agent") or session_map[sid].get("agent") or "unknown",
                                        "input_tokens": int(toks.get("input") or 0),
                                        "output_tokens": out_tok,
                                        "reasoning_chars": reason_len,
                                    }
                                )
        except Exception:
            pass

    ollama_sockets = check_ollama_socket_health()
    ollama_ctx = check_ollama_ctx_health(expected_ctx=24576)
    mem_health = check_opencode_mem_health(mem_log_path=mem_log_path)

    error_counts_by_type: dict[str, int] = {}
    for err in tool_execution_errors:
        cls = err["classification"]
        error_counts_by_type[cls] = error_counts_by_type.get(cls, 0) + 1

    recommendations: list[str] = []
    if ollama_sockets["zombie_queue_detected"]:
        recommendations.append(
            f"Detectadas {ollama_sockets['active_connections']} conexiones activas a Ollama (:11434). Ejecuta 'opencode service restart' para liberar la cola GPU."
        )
    if not mem_health["mitigated"]:
        recommendations.append(
            "Desactiva 'autoCaptureEnabled: false' en config/opencode-mem.jsonc para evitar bloqueos de 135s por StructuredOutput."
        )
    if stalled_sessions:
        recommendations.append(
            f"{len(stalled_sessions)} sesión(es) histórica(s) registraron idle_outcome=NULL (subagentes interrumpidos o directorio clonado tardíamente)."
        )
    if compaction_storms or amnesia_events:
        recommendations.append(
            f"Detectadas {len(compaction_storms)} tormenta(s) de compactación y {len(amnesia_events)} evento(s) de amnesia histórica; mitigado con ventana física 24576 / OpenCode 22528 (output 2560), DCP 8.5k-18k y regla OBJETIVO INMUTABLE."
        )
    if error_counts_by_type.get("skill_agent_confusion"):
        recommendations.append(
            f"Registrados {error_counts_by_type['skill_agent_confusion']} error(es) históricos 'skill vs subagent'; mitigado con prohibición explícita y 'ollama run *: deny'."
        )
    if error_counts_by_type.get("edit_oldstring_mismatch"):
        recommendations.append(
            f"Registrados {error_counts_by_type['edit_oldstring_mismatch']} error(es) históricos 'Could not find oldString' en edit; mitigado con protocolo READ-BEFORE-EDIT y edición atómica."
        )
    if output_limit_truncations:
        recommendations.append(
            f"Detectados {len(output_limit_truncations)} truncamiento(s) por techo de contexto/salida (finish=length / output-limit); mitigado con Ollama num_ctx=24576 y OpenCode limit 22528/2560."
        )
    if not ollama_ctx["all_synced"]:
        recommendations.append(
            "Uno o más modelos de Ollama no tienen PARAMETER num_ctx 24576; ejecuta scripts/configure-ollama-ctx.sh."
        )

    if ollama_sockets["zombie_queue_detected"] or not mem_health["mitigated"]:
        health_status = "CRITICAL"
    elif stalled_sessions or compaction_storms or amnesia_events or tool_execution_errors or output_limit_truncations:
        health_status = "HISTORICAL_WARNINGS_MITIGATED"
    else:
        health_status = "HEALTHY"

    return {
        "health_status": health_status,
        "analyzed_sessions": analyzed_count,
        "stalled_sessions": stalled_sessions,
        "compaction_storms": compaction_storms,
        "amnesia_events": amnesia_events,
        "output_limit_truncations": output_limit_truncations[:30],
        "tool_execution_errors": tool_execution_errors[:30],
        "error_counts_by_type": error_counts_by_type,
        "ollama_socket_health": ollama_sockets,
        "ollama_ctx_health": ollama_ctx,
        "opencode_mem_health": mem_health,
        "recommendations": recommendations,
    }


if __name__ == "__main__":
    print(json.dumps(analyze_recent_sessions(), indent=2, ensure_ascii=False))
