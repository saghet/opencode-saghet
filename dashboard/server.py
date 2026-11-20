#!/usr/bin/env python3
"""Saghet Control Center — Backend de telemetría real e interacción para OpenCode-Saghet."""

from __future__ import annotations

import argparse
import concurrent.futures
import http.server
import json
import os
import re
import shutil
import socketserver
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent
REPO_DIR = DASHBOARD_DIR.parent
ASSETS_DIR = REPO_DIR / "assets"
OPENCODE_CONFIG_DIR = Path.home() / ".config" / "opencode"
OPENCODE_DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
OPENCODE_BIN = "/usr/bin/opencode" if Path("/usr/bin/opencode").is_file() else (shutil.which("opencode") or "opencode")

_PREV_CPU_TIMES: tuple[int, int] | None = None
_JOBS_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _format_opencode_line(raw_line: str) -> str:
    clean = _ANSI_RE.sub("", raw_line)
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


def get_opencode_config_summary():
    cfg_path = OPENCODE_CONFIG_DIR / "opencode.json"
    if not cfg_path.exists():
        return {"agents": {}, "mcp": {}, "plugins": [], "default_agent": None, "model": None}
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        mcp_summary = {
            name: {
                "type": spec.get("type"),
                "enabled": bool(spec.get("enabled", True)),
            }
            for name, spec in cfg.get("mcp", {}).items()
        }
        return {
            "default_agent": cfg.get("default_agent"),
            "model": cfg.get("model"),
            "plugins": cfg.get("plugins", []),
            "mcp": mcp_summary,
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
    except Exception:
        return {"agents": {}, "mcp": {}, "plugins": [], "default_agent": None, "model": None}


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


def collect_telemetry():
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        f_agents = ex.submit(run_cmd_json, ["opencode", "api", "agent.list"])
        f_sessions = ex.submit(run_cmd_json, ["opencode", "api", "session.list"])
        f_providers = ex.submit(run_cmd_json, ["opencode", "api", "provider.list"])
        f_projects = ex.submit(run_cmd_json, ["opencode", "api", "project.list"])
        f_ollama_ps = ex.submit(fetch_json, "http://127.0.0.1:11434/api/ps")
        f_ollama_tags = ex.submit(fetch_json, "http://127.0.0.1:11434/api/tags")
        f_gpu = ex.submit(get_gpu_stats)
        f_mem = ex.submit(check_port, "http://127.0.0.1:4747/")

        agents_api = f_agents.result()
        sessions_api = f_sessions.result()
        providers_api = f_providers.result()
        projects_api = f_projects.result()
        ollama_ps = f_ollama_ps.result()
        ollama_tags = f_ollama_tags.result()
        gpu_stats = f_gpu.result()
        mem_up = f_mem.result()

    cfg = get_opencode_config_summary()

    sessions = (sessions_api or {}).get("data", [])[:30]
    token_totals = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0}
    projects_map: dict[str, dict] = {}

    raw_projects = projects_api if isinstance(projects_api, list) else get_projects_from_db()
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
        "opencode_server_up": sessions_api is not None,
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
        "agents_live": (agents_api or {}).get("data", []),
        "providers": (providers_api or {}).get("data", []),
        "sessions": sessions,
        "projects": sorted(projects_map.values(), key=lambda x: x["last_updated"], reverse=True),
        "skills": get_skills_list(),
        "databases": get_db_sources(),
        "benchmarks": get_benchmarks(),
        "token_totals": token_totals,
    }


class SaghetHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def _send_json(self, status: int, data: dict | list):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/telemetry":
            self._send_json(200, collect_telemetry())
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
                }
            if payload["status"] == "running":
                sess = run_cmd_json(["opencode", "api", "session.list"], timeout=2.0)
                active = [
                    {"agent": s.get("agent"), "title": (s.get("title") or "")[:40]}
                    for s in (sess or {}).get("data", [])[:8]
                    if not s.get("outcome")
                ]
                payload["active_subagents"] = active
            self._send_json(200, payload)
            return

        if parsed.path == "/api/session/messages":
            qs = urllib.parse.parse_qs(parsed.query)
            sid = (qs.get("id") or [""])[0].strip()
            if not sid:
                self._send_json(400, {"error": "Missing session id"})
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
                self._send_json(200, {"ok": res.returncode == 0, "output": res.stdout + res.stderr})
            except Exception as e:
                self._send_json(500, {"ok": False, "output": str(e)})
            return

        if parsed.path.startswith("/assets/"):
            rel = parsed.path[len("/assets/"):].lstrip("/")
            target = (ASSETS_DIR / rel).resolve()
            if str(target).startswith(str(ASSETS_DIR.resolve())) and target.is_file():
                ctype = "image/svg+xml" if target.suffix == ".svg" else "application/octet-stream"
                if target.suffix == ".png":
                    ctype = "image/png"
                data = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
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
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/session/prompt":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"error": "Invalid JSON"})
                return

            prompt = (body.get("prompt") or "").strip()
            agent = (body.get("agent") or "saghet-orchestrator").strip()
            model = (body.get("model") or "").strip()
            directory = (body.get("directory") or str(REPO_DIR)).strip()
            if not prompt:
                self._send_json(400, {"error": "Prompt cannot be empty"})
                return

            cmd = [OPENCODE_BIN, "run", "--agent", agent, "--format", "json", "--auto"]
            if model:
                cmd.extend(["--model", model])
            cmd.append(prompt)

            cwd = directory if Path(directory).is_dir() else str(REPO_DIR)
            job_id = uuid.uuid4().hex[:12]
            env = os.environ.copy()
            env["NO_COLOR"] = "1"
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            with _JOBS_LOCK:
                _JOBS[job_id] = {
                    "proc": proc,
                    "status": "running",
                    "started_at": time.time(),
                    "lines": [],
                    "returncode": None,
                }

            def _reader(jid: str, p: subprocess.Popen):
                try:
                    if p.stdout:
                        for line in p.stdout:
                            formatted = _format_opencode_line(line)
                            if formatted:
                                with _JOBS_LOCK:
                                    _JOBS[jid]["lines"].append(formatted)
                    rc = p.wait()
                    with _JOBS_LOCK:
                        if _JOBS[jid]["status"] != "cancelled":
                            _JOBS[jid]["status"] = "succeeded" if rc == 0 else "error"
                        _JOBS[jid]["returncode"] = rc
                except Exception as exc:
                    with _JOBS_LOCK:
                        _JOBS[jid]["lines"].append(f"\n[ERROR] {exc}\n")
                        _JOBS[jid]["status"] = "error"

            threading.Thread(target=_reader, args=(job_id, proc), daemon=True).start()
            self._send_json(200, {"ok": True, "job_id": job_id, "status": "running"})
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
                if proc and proc.poll() is None:
                    proc.terminate()
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

            target_dir = Path((body.get("directory") or "").strip()).expanduser()
            if not str(target_dir):
                self._send_json(400, {"error": "Directorio requerido"})
                return
            if body.get("create_if_missing"):
                target_dir.mkdir(parents=True, exist_ok=True)
            if not target_dir.is_dir():
                self._send_json(400, {"error": f"No existe el directorio: {target_dir}"})
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
                self._send_json(
                    200,
                    {
                        "ok": res.returncode == 0,
                        "directory": str(target_dir),
                        "output": res.stdout or res.stderr,
                    },
                )
            except Exception as e:
                self._send_json(500, {"ok": False, "error": str(e)})
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
