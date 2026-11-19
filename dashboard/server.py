#!/usr/bin/env python3
"""Saghet Control Center — Backend de telemetría real para OpenCode-Saghet."""

from __future__ import annotations

import argparse
import http.server
import json
import os
import socketserver
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent
OPENCODE_CONFIG_DIR = Path.home() / ".config" / "opencode"


def run_cmd_json(cmd: list[str], timeout: float = 4.0):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
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
                info[k.strip()] = int(v.strip().split()[0])  # KiB
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


def check_port(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as r:
            return 200 <= r.status < 500
    except urllib.error.HTTPError as e:
        return 200 <= e.code < 500
    except Exception:
        return False


def collect_telemetry():
    agents_api = run_cmd_json(["opencode", "api", "agent.list"])
    sessions_api = run_cmd_json(["opencode", "api", "session.list"])
    providers_api = run_cmd_json(["opencode", "api", "provider.list"])

    ollama_ps = fetch_json("http://127.0.0.1:11434/api/ps")
    ollama_tags = fetch_json("http://127.0.0.1:11434/api/tags")
    cfg = get_opencode_config_summary()

    sessions = (sessions_api or {}).get("data", [])[:25]
    token_totals = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0}
    for s in sessions:
        t = s.get("tokens") or {}
        token_totals["input"] += t.get("input", 0)
        token_totals["output"] += t.get("output", 0)
        token_totals["reasoning"] += t.get("reasoning", 0)
        token_totals["cache_read"] += (t.get("cache") or {}).get("read", 0)

    return {
        "opencode_server_up": sessions_api is not None,
        "opencode_mem_up": check_port("http://127.0.0.1:4747/"),
        "gpu": get_gpu_stats(),
        "ram": get_ram_stats(),
        "ollama": {
            "up": ollama_tags is not None,
            "running": (ollama_ps or {}).get("models", []),
            "models_count": len((ollama_tags or {}).get("models", [])),
            "models": [
                {"name": m.get("name"), "size_gb": round((m.get("size", 0) / 1e9), 2)}
                for m in (ollama_tags or {}).get("models", [])
            ],
        },
        "config": cfg,
        "agents_live": (agents_api or {}).get("data", []),
        "providers": (providers_api or {}).get("data", []),
        "sessions": sessions,
        "token_totals": token_totals,
    }


class SaghetHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/api/telemetry":
            payload = json.dumps(collect_telemetry()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return
        super().do_GET()

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
