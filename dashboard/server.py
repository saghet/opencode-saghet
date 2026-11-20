#!/usr/bin/env python3
"""Saghet Control Center — Backend blindado (P0 Security) y telemetría real para OpenCode-Saghet."""

from __future__ import annotations

import argparse
import concurrent.futures
import hmac
import http.server
import json
import os
import re
import secrets
import shutil
import signal
import socket
import socketserver
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent
REPO_DIR = DASHBOARD_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.eval.model_lab import SmartModelRouter, load_evaluation_matrix, run_live_model_probe
from scripts.harness.acp_adapter import DecoupledACPAdapter, set_harness_enabled
from scripts.harness.workflow_engine import HarnessTaskBoard, HarnessWorkflowEngine, get_execution_traces
from scripts.memory.hierarchical_memory import HierarchicalMemoryStore
from scripts.supervisor.gentle_ai_bridge import get_gentle_ai_status
from scripts.supervisor.quality_supervisor import QualitySupervisor, get_decisions
from scripts.supervisor.worktree_manager import list_worktrees
ASSETS_DIR = REPO_DIR / "assets"
OPENCODE_CONFIG_DIR = Path.home() / ".config" / "opencode"
OPENCODE_DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
SAGHET_STATE_DIR = Path.home() / ".local" / "share" / "opencode-saghet"
AUDIT_LOG_PATH = SAGHET_STATE_DIR / "audit.log"
TOKEN_FILE_PATH = OPENCODE_CONFIG_DIR / ".saghet-dashboard-token"
OPENCODE_BIN = "/usr/bin/opencode" if Path("/usr/bin/opencode").is_file() else (shutil.which("opencode") or "opencode")

MAX_CONCURRENT_JOBS = int(os.environ.get("SAGHET_MAX_JOBS", "1"))
MAX_STORED_JOBS = 50
MAX_JOB_LINES = 4000
JOB_TIMEOUT_SECONDS = int(os.environ.get("SAGHET_JOB_TIMEOUT", "900"))

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
FORBIDDEN_SYSTEM_PREFIXES = (
    "/etc",
    "/root",
    "/usr",
    "/var",
    "/boot",
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/sbin",
    "/bin",
    "/lib",
    "/lib64",
)
FORBIDDEN_HOME_DOTDIRS = {
    ".ssh",
    ".gnupg",
    ".aws",
    ".config",
    ".local",
    ".cargo",
    ".opencode-mem",
    ".gemini",
    ".pki",
    ".password-store",
    ".docker",
    ".kube",
}

_PREV_CPU_TIMES: tuple[int, int] | None = None
_JOBS_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}
_AUDIT_LOCK = threading.Lock()
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_AGENT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_DESTRUCTIVE_PROMPT_RE = re.compile(
    r"(\brm\s+-[rRfF]+\s+(/|~|\$HOME)\b|\bDROP\s+(DATABASE|SCHEMA|TABLE)\b|\bTRUNCATE\s+TABLE\b|\bgit\s+push\s+.*--force\b|\bmkfs\b|\bdd\s+if=)",
    re.IGNORECASE,
)
_SECRET_ACCESS_RE = re.compile(
    r"(\.saghet-dashboard-token|\.opencode-mem/\.auth-token|\.env\.db\b|/service\.json\b|\.ssh/id_(rsa|ed25519|ecdsa))",
    re.IGNORECASE,
)
_SECRET_REDACT_RE = re.compile(
    r"((?:OADE_PG_(?:READER|WRITER)_PASS|SAGHET_DASHBOARD_TOKEN|Authorization:\s*Bearer|api[_-]?key|secret|password)\s*[=:]\s*)([^\s\"']+)",
    re.IGNORECASE,
)


def _init_security_token() -> str:
    env_tok = os.environ.get("SAGHET_DASHBOARD_TOKEN", "").strip()
    if env_tok and len(env_tok) >= 16:
        return env_tok
    try:
        OPENCODE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if TOKEN_FILE_PATH.is_file():
            tok = TOKEN_FILE_PATH.read_text(encoding="utf-8").strip()
            if len(tok) >= 32:
                os.chmod(TOKEN_FILE_PATH, 0o600)
                return tok
        tok = secrets.token_hex(32)
        TOKEN_FILE_PATH.write_text(tok + "\n", encoding="utf-8")
        os.chmod(TOKEN_FILE_PATH, 0o600)
        return tok
    except Exception:
        return secrets.token_hex(32)


DASHBOARD_TOKEN = _init_security_token()
SESSION_COOKIE_VALUE = hmac.new(DASHBOARD_TOKEN.encode("utf-8"), b"saghet-matrix-session-v1", "sha256").hexdigest()


def write_audit_event(action: str, status: str, details: dict | None = None, client: str = "127.0.0.1"):
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "epoch_ms": int(time.time() * 1000),
        "client": client,
        "action": action,
        "status": status,
        "details": details or {},
    }
    try:
        with _AUDIT_LOCK:
            SAGHET_STATE_DIR.mkdir(parents=True, exist_ok=True)
            with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            os.chmod(AUDIT_LOG_PATH, 0o600)
    except Exception:
        pass


def get_recent_audit_events(limit: int = 40) -> list[dict]:
    if not AUDIT_LOG_PATH.is_file():
        return []
    try:
        lines = AUDIT_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        out = []
        for raw in reversed(lines[-limit:]):
            if raw.strip():
                out.append(json.loads(raw))
        return out
    except Exception:
        return []


def _redact_secrets(text: str) -> str:
    if not text:
        return text
    redacted = _SECRET_REDACT_RE.sub(r"\1[REDACTED]", text)
    if DASHBOARD_TOKEN and DASHBOARD_TOKEN in redacted:
        redacted = redacted.replace(DASHBOARD_TOKEN, "[REDACTED_DASHBOARD_TOKEN]")
    return redacted


def _format_opencode_line(raw_line: str) -> str:
    clean = _redact_secrets(_ANSI_RE.sub("", raw_line))
    stripped = clean.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            ev = json.loads(stripped)
            etype = ev.get("type", "")
            part = ev.get("part") or {}
            if etype == "text":
                return (part.get("text") or ev.get("text") or "") + "\n"
            if etype == "tool_use":
                tool = part.get("tool") or "tool"
                st = (part.get("state") or {}).get("status") or ""
                title = (part.get("state") or {}).get("title") or ""
                return f"▸ [{tool}] {st} {title}\n"
            if etype == "step_start":
                return "▸ [step] iniciando paso...\n"
            if etype == "error":
                return f"[ERROR] {ev.get('error') or part}\n"
            return ""
        except Exception:
            pass
    return clean


def _terminate_process_tree(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            return
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _prune_old_jobs_locked() -> None:
    if len(_JOBS) <= MAX_STORED_JOBS:
        return
    finished = [
        (jid, j["started_at"])
        for jid, j in _JOBS.items()
        if j.get("status") in {"succeeded", "error", "cancelled"}
    ]
    finished.sort(key=lambda x: x[1])
    while len(_JOBS) > MAX_STORED_JOBS and finished:
        old_id, _ = finished.pop(0)
        _JOBS.pop(old_id, None)


def run_cmd_json(cmd: list[str], timeout: float = 4.0):
    resolved = [OPENCODE_BIN if i == 0 and part == "opencode" else part for i, part in enumerate(cmd)]
    try:
        res = subprocess.run(resolved, capture_output=True, text=True, timeout=timeout, check=False)
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout)
    except Exception:
        pass
    return None


def fetch_json(url: str, timeout: float = 2.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def get_cpu_stats() -> dict:
    global _PREV_CPU_TIMES
    usage_pct = 0.0
    model_name = "CPU"
    cores = os.cpu_count() or 1
    load_1m = 0.0

    try:
        with open("/proc/loadavg", encoding="utf-8") as f:
            load_1m = float(f.read().split()[0])
    except Exception:
        pass

    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("model name"):
                    model_name = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass

    try:
        with open("/proc/stat", encoding="utf-8") as f:
            parts = f.readline().split()[1:]
            vals = [int(x) for x in parts[:8]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            total = sum(vals)
            if _PREV_CPU_TIMES is not None:
                prev_idle, prev_total = _PREV_CPU_TIMES
                dt = total - prev_total
                di = idle - prev_idle
                if dt > 0:
                    usage_pct = round(100.0 * (1.0 - (di / dt)), 1)
            else:
                usage_pct = round(min(100.0, (load_1m / max(1, cores)) * 100.0), 1)
            _PREV_CPU_TIMES = (idle, total)
    except Exception:
        pass

    return {
        "model": model_name,
        "cores": cores,
        "load_1m": load_1m,
        "usage_pct": usage_pct,
    }


def get_gpu_stats():
    try:
        res = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2.5,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = [p.strip() for p in res.stdout.strip().splitlines()[0].split(",")]
            if len(parts) >= 6:
                return {
                    "available": True,
                    "name": parts[0],
                    "utilization_pct": float(parts[1]),
                    "vram_used_mib": float(parts[2]),
                    "vram_total_mib": float(parts[3]),
                    "temp_c": float(parts[4]),
                    "power_w": float(parts[5]),
                }
    except Exception:
        pass
    return {"available": False}


def get_ram_stats():
    info = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k.strip()] = int(v.strip().split()[0])
        total = info.get("MemTotal", 0) / 1024
        avail = info.get("MemAvailable", 0) / 1024
        return {
            "total_mib": round(total, 1),
            "used_mib": round(total - avail, 1),
            "available_mib": round(avail, 1),
        }
    except Exception:
        return {}


def _load_raw_opencode_config() -> dict:
    for candidate in (OPENCODE_CONFIG_DIR / "opencode.json", REPO_DIR / "config" / "opencode.json.tpl"):
        if candidate.is_file():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
    return {}


def get_opencode_config_summary():
    cfg = _load_raw_opencode_config()
    if not cfg:
        return {"agents": {}, "mcp": {}, "plugins": [], "default_agent": None, "model": None, "models_allowlist": []}
    mcp_summary = {
        name: {
            "type": spec.get("type"),
            "enabled": bool(spec.get("enabled", True)),
        }
        for name, spec in cfg.get("mcp", {}).items()
    }
    models_allowlist: set[str] = set()
    if cfg.get("model"):
        models_allowlist.add(str(cfg["model"]))
    if cfg.get("small_model"):
        models_allowlist.add(str(cfg["small_model"]))
    for prov_id, prov_spec in (cfg.get("provider") or {}).items():
        for mod_id in (prov_spec.get("models") or {}).keys():
            models_allowlist.add(f"{prov_id}/{mod_id}")
            models_allowlist.add(mod_id)
    for agent_spec in (cfg.get("agent") or {}).values():
        if agent_spec.get("model"):
            models_allowlist.add(str(agent_spec["model"]))

    return {
        "default_agent": cfg.get("default_agent"),
        "model": cfg.get("model"),
        "plugins": cfg.get("plugins", []),
        "mcp": mcp_summary,
        "models_allowlist": sorted(models_allowlist),
        "agents": {
            k: {
                "mode": v.get("mode", "subagent"),
                "model": v.get("model", cfg.get("model")),
                "description": v.get("description", ""),
                "tools": v.get("tools", {}),
            }
            for k, v in cfg.get("agent", {}).items()
        },
    }


def is_valid_agent(agent: str) -> bool:
    if not agent or not _AGENT_NAME_RE.match(agent):
        return False
    cfg = get_opencode_config_summary()
    return agent in (cfg.get("agents") or {})


def is_valid_model(model: str) -> bool:
    if not model:
        return True
    if model.startswith("-") or not _MODEL_NAME_RE.match(model):
        return False
    cfg = get_opencode_config_summary()
    allowed = set(cfg.get("models_allowlist") or [])
    if model in allowed:
        return True
    tags = fetch_json("http://127.0.0.1:11434/api/tags", timeout=1.5) or {}
    for m in tags.get("models", []):
        name = m.get("name")
        if name and model in {name, f"ollama/{name}"}:
            return True
    return False


def validate_project_directory(raw_dir: str, create_if_missing: bool = False) -> tuple[bool, Path | None, str]:
    cleaned = (raw_dir or "").strip()
    if not cleaned or "\x00" in cleaned:
        return False, None, "Directorio vacío o inválido"
    try:
        expanded = Path(cleaned).expanduser()
        target = expanded.resolve(strict=False)
    except Exception as exc:
        return False, None, f"Ruta inválida: {exc}"

    target_str = str(target)
    if target_str == "/" or target == Path.home().resolve():
        return False, None, "No se permite operar directamente sobre la raíz o $HOME completo"

    for prefix in FORBIDDEN_SYSTEM_PREFIXES:
        if target_str == prefix or target_str.startswith(prefix + "/"):
            return False, None, f"Directorio del sistema restringido por seguridad: {prefix}"

    home_resolved = Path.home().resolve()
    try:
        rel_home = target.relative_to(home_resolved)
        parts = rel_home.parts
        if parts and parts[0] in FORBIDDEN_HOME_DOTDIRS:
            return False, None, f"Directorio sensible protegido: ~/{parts[0]}"
        if any(p.startswith(".") and p in FORBIDDEN_HOME_DOTDIRS for p in parts):
            return False, None, "Ruta contiene un directorio oculto restringido"
    except ValueError:
        tmp_resolved = Path(tempfile.gettempdir()).resolve()
        try:
            target.relative_to(tmp_resolved)
        except ValueError:
            return False, None, "Solo se permiten directorios de proyectos dentro del espacio del usuario ($HOME)"

    if create_if_missing and not target.exists():
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return False, None, f"No se pudo crear el directorio: {exc}"

    if not target.is_dir():
        return False, None, f"No existe el directorio: {target}"

    return True, target, "OK"


def prepare_isolated_worktree(base_dir: Path, job_id: str) -> tuple[Path, str | None]:
    """Crea un git worktree aislado para modificaciones de riesgo si base_dir es un repositorio Git."""
    try:
        chk = subprocess.run(
            ["git", "-C", str(base_dir), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if chk.returncode != 0:
            return base_dir, None
        wt_root = SAGHET_STATE_DIR / "worktrees"
        wt_root.mkdir(parents=True, exist_ok=True)
        wt_path = wt_root / f"{base_dir.name}-{job_id}"
        branch_name = f"saghet/job-{job_id}"
        res = subprocess.run(
            ["git", "-C", str(base_dir), "worktree", "add", str(wt_path), "-b", branch_name],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if res.returncode == 0 and wt_path.is_dir():
            write_audit_event("worktree.create", "ok", {"base": str(base_dir), "worktree": str(wt_path), "branch": branch_name})
            return wt_path, branch_name
    except Exception:
        pass
    return base_dir, None


def get_skills_list() -> list[dict]:
    skills = []
    skills_dir = OPENCODE_CONFIG_DIR / "skills"
    if skills_dir.exists():
        for entry in sorted(skills_dir.iterdir()):
            skill_md = entry / "SKILL.md"
            if entry.is_dir() and skill_md.exists():
                skills.append({"name": entry.name, "path": str(skill_md)})
    return skills


def get_db_sources() -> list[dict]:
    db_file = OPENCODE_CONFIG_DIR / "dbhub.toml"
    sources = []
    if not db_file.exists():
        return sources
    try:
        current: dict | None = None
        for raw in db_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line == "[[sources]]":
                if current:
                    sources.append(current)
                current = {}
            elif current is not None and "=" in line and not line.startswith("#"):
                k, v = [x.strip() for x in line.split("=", 1)]
                v = v.strip('"').strip("'")
                if k in {"id", "type", "readonly", "description"}:
                    current[k] = v
        if current:
            sources.append(current)
    except Exception:
        pass
    return sources


def get_benchmarks() -> dict:
    bench_path = REPO_DIR / "benchmarks" / "rtx4060_saghet.json"
    if not bench_path.exists():
        return {}
    try:
        return json.loads(bench_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def check_port(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as r:
            return 200 <= r.status < 500
    except urllib.error.HTTPError as e:
        return 200 <= e.code < 500
    except Exception:
        return False


def check_tcp_port(host: str, port: int, timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def get_projects_from_db() -> list[dict]:
    if not OPENCODE_DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{OPENCODE_DB_PATH}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, worktree, vcs, name, time_created, time_updated FROM project").fetchall()
        conn.close()
        out = []
        for r in rows:
            d = r["worktree"]
            if d:
                out.append(
                    {
                        "id": r["id"],
                        "canonical": d,
                        "name": r["name"] or Path(d).name or d,
                        "vcs": r["vcs"],
                        "time": {"created": r["time_created"] or 0, "updated": r["time_updated"] or 0},
                    }
                )
        return out
    except Exception:
        return []


def get_sessions_from_db(limit: int = 30) -> list[dict] | None:
    if not OPENCODE_DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{OPENCODE_DB_PATH}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, project_id, parent_id, directory, title, agent, model,
                   tokens_input, tokens_output, tokens_reasoning, tokens_cache_read,
                   idle_outcome, time_created, time_updated
            FROM session_v2
            ORDER BY time_updated DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()
        sessions = []
        for r in rows:
            sessions.append(
                {
                    "id": r["id"],
                    "projectID": r["project_id"],
                    "parentID": r["parent_id"],
                    "title": r["title"] or r["id"],
                    "agent": r["agent"] or "saghet-orchestrator",
                    "model": r["model"],
                    "outcome": r["idle_outcome"] or "succeeded",
                    "location": {"directory": r["directory"]},
                    "time": {"created": r["time_created"] or 0, "updated": r["time_updated"] or 0},
                    "tokens": {
                        "input": r["tokens_input"] or 0,
                        "output": r["tokens_output"] or 0,
                        "reasoning": r["tokens_reasoning"] or 0,
                        "cache": {"read": r["tokens_cache_read"] or 0},
                    },
                }
            )
        return sessions
    except Exception:
        return None


def collect_telemetry():
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        f_db_sessions = ex.submit(get_sessions_from_db, 30)
        f_db_projects = ex.submit(get_projects_from_db)
        f_ollama_ps = ex.submit(fetch_json, "http://127.0.0.1:11434/api/ps")
        f_ollama_tags = ex.submit(fetch_json, "http://127.0.0.1:11434/api/tags")
        f_gpu = ex.submit(get_gpu_stats)
        f_mem = ex.submit(check_port, "http://127.0.0.1:4747/")

        db_sessions = f_db_sessions.result()
        raw_projects = f_db_projects.result()
        ollama_ps = f_ollama_ps.result()
        ollama_tags = f_ollama_tags.result()
        gpu_stats = f_gpu.result()
        mem_up = f_mem.result()

    if db_sessions is not None:
        sessions = db_sessions
        opencode_up = check_tcp_port("127.0.0.1", 49374) or OPENCODE_DB_PATH.exists()
    else:
        sessions_api = run_cmd_json(["opencode", "api", "session.list"])
        sessions = (sessions_api or {}).get("data", [])[:30]
        opencode_up = sessions_api is not None

    cfg = get_opencode_config_summary()
    raw_cfg = _load_raw_opencode_config()
    agents_live = [{"id": name, **spec} for name, spec in (cfg.get("agents") or {}).items()]
    providers_live = [
        {
            "id": pid,
            "name": pspec.get("name", pid),
            "activation": "enabled",
            "settings": {"baseURL": (pspec.get("options") or {}).get("baseURL", "")},
        }
        for pid, pspec in (raw_cfg.get("provider") or {}).items()
    ]

    token_totals = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0}
    projects_map: dict[str, dict] = {}

    for pr in raw_projects:
        canon = pr.get("canonical") or pr.get("worktree")
        if not canon:
            continue
        t = pr.get("time") or {}
        ts = max(t.get("active", 0), t.get("updated", 0), t.get("created", 0))
        existing = projects_map.get(canon)
        if existing:
            existing["last_updated"] = max(existing["last_updated"], ts)
            if pr.get("vcs") and not existing.get("vcs"):
                existing["vcs"] = pr.get("vcs")
        else:
            projects_map[canon] = {
                "id": pr.get("id"),
                "name": pr.get("name") or Path(canon).name or canon,
                "directory": canon,
                "vcs": pr.get("vcs"),
                "sessions": 0,
                "last_updated": ts,
            }

    for s in sessions:
        t = s.get("tokens") or {}
        token_totals["input"] += t.get("input", 0)
        token_totals["output"] += t.get("output", 0)
        token_totals["reasoning"] += t.get("reasoning", 0)
        token_totals["cache_read"] += (t.get("cache") or {}).get("read", 0)
        loc_dir = (s.get("location") or {}).get("directory")
        if loc_dir:
            p = projects_map.setdefault(
                loc_dir,
                {
                    "id": s.get("projectID"),
                    "name": Path(loc_dir).name or loc_dir,
                    "directory": loc_dir,
                    "vcs": None,
                    "sessions": 0,
                    "last_updated": 0,
                },
            )
            p["sessions"] += 1
            p["last_updated"] = max(p["last_updated"], (s.get("time") or {}).get("updated", 0))

    if str(REPO_DIR) not in projects_map:
        projects_map[str(REPO_DIR)] = {
            "id": "saghet-repo",
            "name": REPO_DIR.name,
            "directory": str(REPO_DIR),
            "vcs": "git",
            "sessions": 0,
            "last_updated": int(time.time() * 1000),
        }

    return {
        "opencode_server_up": opencode_up,
        "opencode_mem_up": mem_up,
        "cpu": get_cpu_stats(),
        "gpu": gpu_stats,
        "ram": get_ram_stats(),
        "ollama": {
            "up": ollama_tags is not None,
            "running": (ollama_ps or {}).get("models", []),
            "models_count": len((ollama_tags or {}).get("models", [])),
            "models": [
                {
                    "name": m.get("name"),
                    "size_gb": round((m.get("size", 0) / 1e9), 2),
                    "parameter_size": (m.get("details") or {}).get("parameter_size"),
                    "quantization": (m.get("details") or {}).get("quantization_level"),
                }
                for m in (ollama_tags or {}).get("models", [])
            ],
        },
        "config": cfg,
        "agents_live": agents_live,
        "providers": providers_live,
        "sessions": sessions,
        "projects": sorted(projects_map.values(), key=lambda x: x["last_updated"], reverse=True),
        "skills": get_skills_list(),
        "databases": get_db_sources(),
        "benchmarks": get_benchmarks(),
        "token_totals": token_totals,
        "evaluation_matrix": load_evaluation_matrix(),
        "security": {
            "auth_enabled": True,
            "csrf_protection": True,
            "dns_rebinding_guard": True,
            "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
            "audit_events": get_recent_audit_events(25),
            "worktrees": list_worktrees(REPO_DIR),
        },
        "gentle_ai": get_gentle_ai_status(REPO_DIR),
        "supervisor": {
            "recent_decisions": len(get_decisions(30)),
            "decisions": get_decisions(20),
        },
        "memory": HierarchicalMemoryStore().get_summary(),
        "harness": {
            "status": DecoupledACPAdapter().get_status(),
            "task_board": HarnessTaskBoard().list_tasks()[:30],
            "traces": get_execution_traces(limit=30),
        },
    }


class SaghetHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else "unknown"

    def _add_security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
        )

    def _send_json(self, status: int, data: dict | list):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self._add_security_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _check_host_and_origin(self, require_same_origin: bool = False) -> tuple[bool, str]:
        """Protección contra DNS Rebinding y Cross-Origin CSRF."""
        raw_host = (self.headers.get("Host") or "").strip()
        if not raw_host:
            return False, "Cabecera Host ausente"
        host_only = raw_host.split(":")[0].strip().lower()
        if raw_host.startswith("[") and "]" in raw_host:
            host_only = raw_host[: raw_host.index("]") + 1].lower()
        if host_only not in ALLOWED_HOSTS:
            return False, f"Host no autorizado (DNS Rebinding bloqueado): {raw_host}"

        sec_fetch_site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if sec_fetch_site == "cross-site":
            return False, "Solicitud cross-site bloqueada (Sec-Fetch-Site: cross-site)"

        origin = (self.headers.get("Origin") or "").strip()
        if origin:
            if origin.lower() == "null":
                return False, "Origin null bloqueado"
            try:
                parsed_orig = urllib.parse.urlparse(origin)
                orig_host = (parsed_orig.hostname or "").lower()
                if orig_host not in ALLOWED_HOSTS:
                    return False, f"Origin externo bloqueado (CSRF): {origin}"
            except Exception:
                return False, "Cabecera Origin malformada"

        referer = (self.headers.get("Referer") or "").strip()
        if require_same_origin and referer and not origin:
            try:
                parsed_ref = urllib.parse.urlparse(referer)
                ref_host = (parsed_ref.hostname or "").lower()
                if ref_host not in ALLOWED_HOSTS:
                    return False, f"Referer externo bloqueado (CSRF): {referer}"
            except Exception:
                return False, "Cabecera Referer malformada"

        return True, "OK"

    def _has_valid_auth_token(self) -> bool:
        """Verifica X-Saghet-Token, Authorization: Bearer o cookie de sesión + X-CSRF-Token."""
        hdr_tok = (self.headers.get("X-Saghet-Token") or "").strip()
        if hdr_tok and hmac.compare_digest(hdr_tok, DASHBOARD_TOKEN):
            return True

        auth_hdr = (self.headers.get("Authorization") or "").strip()
        if auth_hdr.lower().startswith("bearer "):
            bearer_tok = auth_hdr[7:].strip()
            if bearer_tok and hmac.compare_digest(bearer_tok, DASHBOARD_TOKEN):
                return True

        csrf_hdr = (self.headers.get("X-CSRF-Token") or "").strip()
        cookie_hdr = self.headers.get("Cookie") or ""
        if csrf_hdr and hmac.compare_digest(csrf_hdr, DASHBOARD_TOKEN):
            if f"saghet_session={SESSION_COOKIE_VALUE}" in cookie_hdr:
                return True

        return False

    def _serve_index_with_csrf(self):
        index_path = DASHBOARD_DIR / "index.html"
        if not index_path.is_file():
            self.send_error(404)
            return
        html = index_path.read_text(encoding="utf-8")
        meta_tag = f'    <meta name="saghet-csrf-token" content="{DASHBOARD_TOKEN}" />\n  </head>'
        if "</head>" in html and 'name="saghet-csrf-token"' not in html:
            html = html.replace("  </head>", meta_tag, 1)
        payload = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header(
            "Set-Cookie",
            f"saghet_session={SESSION_COOKIE_VALUE}; HttpOnly; SameSite=Strict; Path=/",
        )
        self._add_security_headers()
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        ok_origin, reason = self._check_host_and_origin(require_same_origin=False)
        if not ok_origin:
            write_audit_event("http.get.blocked", "denied", {"path": self.path, "reason": reason}, self._client_ip())
            self._send_json(403, {"ok": False, "error": reason})
            return

        parsed = urllib.parse.urlparse(self.path)

        if parsed.path in {"/", "/index.html"}:
            self._serve_index_with_csrf()
            return

        if parsed.path == "/api/telemetry":
            self._send_json(200, collect_telemetry())
            return

        if parsed.path == "/api/security/status":
            with _JOBS_LOCK:
                running_jobs = sum(1 for j in _JOBS.values() if j.get("status") == "running")
            self._send_json(
                200,
                {
                    "ok": True,
                    "auth_enabled": True,
                    "csrf_protection": True,
                    "dns_rebinding_guard": True,
                    "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
                    "running_jobs": running_jobs,
                    "audit_events": get_recent_audit_events(25),
                },
            )
            return

        if parsed.path == "/api/supervisor/decisions":
            self._send_json(
                200,
                {
                    "ok": True,
                    "gentle_ai": get_gentle_ai_status(REPO_DIR),
                    "decisions": get_decisions(50),
                },
            )
            return

        if parsed.path == "/api/models/evaluation":
            router = SmartModelRouter()
            self._send_json(
                200,
                {
                    "ok": True,
                    "matrix": router.matrix,
                    "active_routes": {
                        spec: router.route(spec, avoid_vram_swap=False)
                        for spec in ("classification", "coding", "architecture", "independent_review", "security_audit")
                    },
                },
            )
            return

        if parsed.path == "/api/memory/status":
            store = HierarchicalMemoryStore()
            self._send_json(200, {"ok": True, **store.get_summary()})
            return

        if parsed.path == "/api/harness/status":
            adapter = DecoupledACPAdapter()
            board = HarnessTaskBoard()
            self._send_json(
                200,
                {
                    "ok": True,
                    "harness": adapter.get_status(),
                    "task_board": board.list_tasks()[:40],
                    "traces": get_execution_traces(limit=40),
                },
            )
            return

        if parsed.path == "/api/session/job":
            qs = urllib.parse.parse_qs(parsed.query)
            jid = (qs.get("id") or [""])[0].strip()
            with _JOBS_LOCK:
                job = _JOBS.get(jid)
                if not job:
                    self._send_json(404, {"error": "Job no encontrado"})
                    return
                payload = {
                    "id": jid,
                    "status": job["status"],
                    "elapsed_s": round(time.time() - job["started_at"], 1),
                    "output": "".join(job["lines"]),
                    "returncode": job["returncode"],
                    "worktree": job.get("worktree"),
                    "branch": job.get("branch"),
                    "supervisor_plan": job.get("supervisor_plan"),
                    "supervisor_evaluation": job.get("supervisor_evaluation"),
                }
            if payload["status"] == "running":
                db_sess = get_sessions_from_db(8) or []
                active = [
                    {"agent": s.get("agent"), "title": (s.get("title") or "")[:40]}
                    for s in db_sess
                    if s.get("outcome") not in {"succeeded", "failed", "error"}
                ]
                payload["active_subagents"] = active
            self._send_json(200, payload)
            return

        if parsed.path == "/api/session/messages":
            qs = urllib.parse.parse_qs(parsed.query)
            sid = (qs.get("id") or [""])[0].strip()
            if not sid or not re.match(r"^[A-Za-z0-9_-]{4,80}$", sid):
                self._send_json(400, {"error": "Invalid or missing session id"})
                return
            msgs = run_cmd_json(["opencode", "api", "session.messages", "--param", f"sessionID={sid}"], timeout=8.0)
            self._send_json(200, msgs or {"data": []})
            return

        if parsed.path == "/api/diagnostics":
            try:
                res = subprocess.run(
                    ["bash", str(REPO_DIR / "doctor.sh")],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                self._send_json(200, {"ok": res.returncode == 0, "output": _redact_secrets(res.stdout + res.stderr)})
            except Exception as e:
                self._send_json(500, {"ok": False, "output": str(e)})
            return

        if parsed.path.startswith("/assets/"):
            rel = parsed.path[len("/assets/") :].lstrip("/")
            target = (ASSETS_DIR / rel).resolve()
            if str(target).startswith(str(ASSETS_DIR.resolve())) and target.is_file():
                ctype = "image/svg+xml" if target.suffix == ".svg" else "application/octet-stream"
                if target.suffix == ".png":
                    ctype = "image/png"
                data = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self._add_security_headers()
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_error(404)
            return

        if parsed.path == "/health":
            self._send_json(200, {"ok": True})
            return

        super().do_GET()

    def do_POST(self):
        ok_origin, reason = self._check_host_and_origin(require_same_origin=True)
        if not ok_origin:
            write_audit_event("http.post.blocked", "denied", {"path": self.path, "reason": reason}, self._client_ip())
            self._send_json(403, {"ok": False, "error": reason})
            return

        if not self._has_valid_auth_token():
            write_audit_event("http.post.unauthorized", "denied", {"path": self.path}, self._client_ip())
            self._send_json(403, {"ok": False, "error": "Token de autenticación ausente o inválido (X-Saghet-Token)"})
            return

        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/session/prompt":
            length = int(self.headers.get("Content-Length", "0"))
            if length > 262144:
                self._send_json(413, {"ok": False, "error": "Payload demasiado grande"})
                return
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "Invalid JSON"})
                return

            prompt = (body.get("prompt") or "").strip()
            agent = (body.get("agent") or "saghet-orchestrator").strip()
            model = (body.get("model") or "").strip()
            directory = (body.get("directory") or str(REPO_DIR)).strip()
            isolate_worktree = bool(body.get("isolate_worktree", False))
            approve_destructive = bool(body.get("approve_destructive", False))

            if not prompt:
                self._send_json(400, {"ok": False, "error": "Prompt cannot be empty"})
                return

            if _SECRET_ACCESS_RE.search(prompt):
                write_audit_event(
                    "session.prompt.secret_blocked",
                    "denied",
                    {"agent": agent, "directory": directory},
                    self._client_ip(),
                )
                self._send_json(403, {"ok": False, "error": "Prompt bloqueado: intento de acceso a archivo secreto protegido"})
                return

            if _DESTRUCTIVE_PROMPT_RE.search(prompt) and not approve_destructive:
                write_audit_event(
                    "session.prompt.destructive_blocked",
                    "denied",
                    {"agent": agent, "directory": directory},
                    self._client_ip(),
                )
                self._send_json(
                    403,
                    {
                        "ok": False,
                        "error": "Operación potencialmente destructiva detectada; requiere aprobación explícita (approve_destructive).",
                    },
                )
                return

            if not is_valid_agent(agent):
                write_audit_event("session.prompt.invalid_agent", "denied", {"agent": agent}, self._client_ip())
                self._send_json(400, {"ok": False, "error": f"Agente no permitido o no registrado: {agent}"})
                return

            if not is_valid_model(model):
                write_audit_event("session.prompt.invalid_model", "denied", {"model": model}, self._client_ip())
                self._send_json(400, {"ok": False, "error": f"Modelo no permitido o malformado: {model}"})
                return

            dir_ok, resolved_dir, dir_reason = validate_project_directory(directory, create_if_missing=False)
            if not dir_ok or resolved_dir is None:
                write_audit_event(
                    "session.prompt.invalid_directory",
                    "denied",
                    {"directory": directory, "reason": dir_reason},
                    self._client_ip(),
                )
                self._send_json(403, {"ok": False, "error": dir_reason})
                return

            with _JOBS_LOCK:
                running_count = sum(1 for j in _JOBS.values() if j.get("status") == "running")
                if running_count >= MAX_CONCURRENT_JOBS:
                    self._send_json(
                        429,
                        {
                            "ok": False,
                            "error": f"Límite de {MAX_CONCURRENT_JOBS} trabajo(s) activo(s) alcanzado (protección de 8 GB VRAM).",
                        },
                    )
                    return

            job_id = uuid.uuid4().hex[:12]
            supervisor = QualitySupervisor()
            sup_plan = supervisor.plan_execution(prompt, directory=resolved_dir)
            exec_dir = resolved_dir
            wt_branch = None
            if isolate_worktree:
                exec_dir, wt_branch = prepare_isolated_worktree(resolved_dir, job_id)

            cmd = [OPENCODE_BIN, "run", "--agent", agent, "--format", "json", "--auto"]
            if model:
                cmd.extend(["--model", model])
            cmd.extend(["--", prompt])

            env = os.environ.copy()
            env["NO_COLOR"] = "1"
            proc = subprocess.Popen(
                cmd,
                cwd=str(exec_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            with _JOBS_LOCK:
                _prune_old_jobs_locked()
                _JOBS[job_id] = {
                    "proc": proc,
                    "status": "running",
                    "started_at": time.time(),
                    "lines": [],
                    "returncode": None,
                    "prompt": prompt,
                    "agent": agent,
                    "model": model,
                    "directory": str(exec_dir),
                    "worktree": str(exec_dir) if wt_branch else None,
                    "branch": wt_branch,
                    "supervisor_plan": sup_plan,
                    "supervisor_evaluation": None,
                }

            write_audit_event(
                "session.prompt.start",
                "running",
                {"job_id": job_id, "agent": agent, "model": model, "directory": str(exec_dir), "branch": wt_branch},
                self._client_ip(),
            )

            def _reader(jid: str, p: subprocess.Popen):
                try:
                    if p.stdout:
                        for line in p.stdout:
                            if time.time() - _JOBS[jid]["started_at"] > JOB_TIMEOUT_SECONDS:
                                _terminate_process_tree(p)
                                with _JOBS_LOCK:
                                    _JOBS[jid]["lines"].append("\n[ERROR] Tiempo máximo de ejecución excedido.\n")
                                    _JOBS[jid]["status"] = "error"
                                break
                            formatted = _format_opencode_line(line)
                            if formatted:
                                with _JOBS_LOCK:
                                    if len(_JOBS[jid]["lines"]) < MAX_JOB_LINES:
                                        _JOBS[jid]["lines"].append(formatted)
                    rc = p.wait(timeout=5)
                    with _JOBS_LOCK:
                        full_out = "".join(_JOBS[jid]["lines"])
                        wt_dir = Path(_JOBS[jid]["worktree"]) if _JOBS[jid].get("worktree") else None
                    sup_eval = supervisor.evaluate_execution(
                        objective=prompt,
                        agent=agent,
                        agent_output=full_out,
                        iteration=1,
                        worktree_path=wt_dir,
                        test_returncode=0 if rc == 0 else rc,
                    )
                    with _JOBS_LOCK:
                        _JOBS[jid]["supervisor_evaluation"] = sup_eval
                        if _JOBS[jid]["status"] not in {"cancelled", "error"}:
                            _JOBS[jid]["status"] = "succeeded" if rc == 0 else "error"
                        _JOBS[jid]["returncode"] = rc
                        final_status = _JOBS[jid]["status"]
                    write_audit_event(
                        "session.prompt.end",
                        final_status,
                        {"job_id": jid, "returncode": rc, "supervisor_verdict": sup_eval.get("verdict")},
                    )
                except Exception as exc:
                    _terminate_process_tree(p)
                    with _JOBS_LOCK:
                        _JOBS[jid]["lines"].append(f"\n[ERROR] {_redact_secrets(str(exc))}\n")
                        _JOBS[jid]["status"] = "error"
                    write_audit_event("session.prompt.error", "error", {"job_id": jid, "error": str(exc)})

            threading.Thread(target=_reader, args=(job_id, proc), daemon=True).start()
            self._send_json(
                200,
                {
                    "ok": True,
                    "job_id": job_id,
                    "status": "running",
                    "directory": str(exec_dir),
                    "branch": wt_branch,
                },
            )
            return

        if parsed.path == "/api/session/job/cancel":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                body = {}
            jid = (body.get("id") or "").strip()
            with _JOBS_LOCK:
                job = _JOBS.get(jid)
                if not job:
                    self._send_json(404, {"error": "Job no encontrado"})
                    return
                proc = job.get("proc")
                job["status"] = "cancelled"
            _terminate_process_tree(proc)
            write_audit_event("session.job.cancel", "cancelled", {"job_id": jid}, self._client_ip())
            self._send_json(200, {"ok": True, "status": "cancelled"})
            return

        if parsed.path == "/api/projects/add":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"error": "Invalid JSON"})
                return

            raw_dir = (body.get("directory") or "").strip()
            create_if_missing = bool(body.get("create_if_missing", False))
            dir_ok, target_dir, dir_reason = validate_project_directory(raw_dir, create_if_missing=create_if_missing)
            if not dir_ok or target_dir is None:
                write_audit_event(
                    "projects.add.blocked",
                    "denied",
                    {"directory": raw_dir, "reason": dir_reason},
                    self._client_ip(),
                )
                self._send_json(403, {"ok": False, "error": dir_reason})
                return

            try:
                res = subprocess.run(
                    [OPENCODE_BIN, "api", "session.create", "--data", "{}"],
                    cwd=str(target_dir),
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
                write_audit_event(
                    "projects.add",
                    "ok" if res.returncode == 0 else "error",
                    {"directory": str(target_dir)},
                    self._client_ip(),
                )
                self._send_json(
                    200,
                    {
                        "ok": res.returncode == 0,
                        "directory": str(target_dir),
                        "output": _redact_secrets(res.stdout or res.stderr),
                    },
                )
            except Exception as e:
                self._send_json(500, {"ok": False, "error": str(e)})
            return

        if parsed.path == "/api/supervisor/plan":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "Invalid JSON"})
                return
            objective = (body.get("objective") or body.get("prompt") or "").strip()
            if not objective:
                self._send_json(400, {"ok": False, "error": "Objective required"})
                return
            sup = QualitySupervisor(max_iterations=int(body.get("max_iterations", 3)))
            plan = sup.plan_execution(objective, directory=REPO_DIR, context_files=body.get("context_files"))
            self._send_json(200, {"ok": True, "plan": plan})
            return

        if parsed.path == "/api/supervisor/evaluate":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "Invalid JSON"})
                return
            sup = QualitySupervisor(max_iterations=int(body.get("max_iterations", 3)))
            decision = sup.evaluate_execution(
                objective=str(body.get("objective") or ""),
                agent=str(body.get("agent") or "senior-developer"),
                agent_output=str(body.get("agent_output") or ""),
                iteration=int(body.get("iteration", 1)),
                is_readonly=body.get("is_readonly"),
                diff_files=body.get("diff_files"),
                test_output=str(body.get("test_output") or ""),
                test_returncode=body.get("test_returncode"),
                reviewer_verdict=body.get("reviewer_verdict"),
                require_tests=body.get("require_tests"),
            )
            self._send_json(200, {"ok": True, "decision": decision})
            return

        if parsed.path == "/api/models/route":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "Invalid JSON"})
                return
            router = SmartModelRouter()
            specialty = str(body.get("specialty") or "coding")
            route_res = router.route(
                specialty=specialty,
                loaded_in_vram=body.get("loaded_in_vram"),
                avoid_vram_swap=bool(body.get("avoid_vram_swap", True)),
                allow_heavy_cpu_offload=bool(body.get("allow_heavy_cpu_offload", False)),
                external_provider_available=bool(body.get("external_provider_available", False)),
            )
            cand = str(body.get("candidate_model") or "").strip()
            if cand:
                can_promo, promo_reason = router.can_promote_model(cand, specialty)
                route_res["promotion_check"] = {"candidate": cand, "allowed": can_promo, "reason": promo_reason}
            self._send_json(200, {"ok": True, "route": route_res})
            return

        if parsed.path == "/api/models/evaluate":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "Invalid JSON"})
                return
            model = str(body.get("model") or "qwen3.5:9b").strip()
            if not is_valid_model(model):
                self._send_json(400, {"ok": False, "error": f"Modelo inválido: {model}"})
                return
            probe = run_live_model_probe(model)
            self._send_json(200, probe)
            return

        if parsed.path == "/api/memory/store":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "Invalid JSON"})
                return
            store = HierarchicalMemoryStore()
            res = store.store_memory(
                tier=str(body.get("tier") or "experience"),
                category=str(body.get("category") or "verified_execution"),
                title=str(body.get("title") or ""),
                content=str(body.get("content") or ""),
                provenance=str(body.get("provenance") or "dashboard:manual"),
                project_path=str(body.get("project_path") or "*"),
                session_id=str(body.get("session_id") or ""),
                context=body.get("context") if isinstance(body.get("context"), dict) else {},
                confidence=float(body.get("confidence", 0.85)),
            )
            self._send_json(200 if res.get("ok") else 400, res)
            return

        if parsed.path == "/api/memory/query":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "Invalid JSON"})
                return
            store = HierarchicalMemoryStore()
            memories = store.retrieve_relevant_memories(
                query=str(body.get("query") or ""),
                project_path=str(body.get("project_path") or "*"),
                session_id=str(body.get("session_id") or ""),
                tiers=body.get("tiers") if isinstance(body.get("tiers"), list) else None,
                min_confidence=float(body.get("min_confidence", 0.60)),
                limit=int(body.get("limit", 6)),
            )
            self._send_json(200, {"ok": True, "count": len(memories), "memories": memories})
            return

        if parsed.path == "/api/harness/toggle":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "Invalid JSON"})
                return
            enabled = bool(body.get("enabled", True))
            cfg = set_harness_enabled(enabled)
            write_audit_event("harness.toggle", "ok", {"enabled": enabled}, self._client_ip())
            self._send_json(200, {"ok": True, "enabled": cfg["enabled"], "config": cfg})
            return

        if parsed.path == "/api/harness/workflow":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "Invalid JSON"})
                return
            title = str(body.get("title") or "Workflow Saghet DAG").strip()
            nodes = body.get("nodes")
            if not isinstance(nodes, list) or not nodes:
                self._send_json(400, {"ok": False, "error": "Se requiere lista 'nodes' no vacía para el DAG"})
                return
            raw_dir = str(body.get("directory") or str(REPO_DIR))
            dir_ok, resolved_dir, dir_reason = validate_project_directory(raw_dir, create_if_missing=False)
            if not dir_ok or resolved_dir is None:
                self._send_json(403, {"ok": False, "error": dir_reason})
                return
            engine = HarnessWorkflowEngine()
            if body.get("background"):
                bg = engine.start_background_workflow(
                    title=title,
                    nodes_spec=nodes,
                    directory=str(resolved_dir),
                    persistent_session_id=body.get("session_id"),
                )
                self._send_json(200, bg)
            else:
                res = engine.execute_workflow(
                    title=title,
                    nodes_spec=nodes,
                    directory=str(resolved_dir),
                    persistent_session_id=body.get("session_id"),
                )
                self._send_json(200 if res.get("ok") else 400, res)
            return

        self.send_error(404)

    def log_message(self, format, *args):
        return


def main():
    parser = argparse.ArgumentParser(description="Saghet Control Center Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4780)
    args = parser.parse_args()

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((args.host, args.port), SaghetHandler) as httpd:
        print(f"Saghet Control Center listening on http://{args.host}:{args.port}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
