#!/usr/bin/env python3
"""Benchmark y supervisión CUDA/VRAM/Ollama para OpenCode-Saghet (RTX 4060 8 GB)."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA_URL = "http://127.0.0.1:11434"
FALLBACK_CHAIN = ["qwen3.5:9b", "qwen3:8b", "qwen3.5:4b", "qwen2.5-coder:7b"]


def get_gpu() -> dict:
    try:
        res = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            p = [x.strip() for x in res.stdout.strip().splitlines()[0].split(",")]
            return {
                "available": True,
                "name": p[0],
                "driver": p[1],
                "gpu_util_pct": float(p[2]),
                "vram_used_mib": float(p[3]),
                "vram_total_mib": float(p[4]),
                "temp_c": float(p[5]),
            }
    except Exception:
        pass
    return {"available": False}


def get_ram_mib() -> dict:
    info = {}
    with open("/proc/meminfo", encoding="utf-8") as f:
        for line in f:
            k, v = line.split(":", 1)
            info[k.strip()] = int(v.strip().split()[0])
    total = info.get("MemTotal", 0) / 1024
    avail = info.get("MemAvailable", 0) / 1024
    return {"total_mib": round(total, 1), "used_mib": round(total - avail, 1)}


def list_ollama_models() -> list[str]:
    with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as r:
        data = json.loads(r.read().decode("utf-8"))
    return [m["name"] for m in data.get("models", [])]


def resolve_model_with_fallback(requested: str, installed: list[str]) -> str:
    if requested in installed:
        return requested
    for candidate in FALLBACK_CHAIN:
        if candidate in installed:
            return candidate
    raise RuntimeError(f"Ningún modelo disponible en Ollama (solicitado: {requested})")


def bench_model(model: str, prompt: str) -> dict:
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {"num_predict": 48, "temperature": 0.1},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    ttft_ms = None
    final_stats = {}
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            for raw in resp:
                chunk = json.loads(raw.decode("utf-8"))
                if ttft_ms is None and (chunk.get("response") or chunk.get("thinking")):
                    ttft_ms = (time.perf_counter() - t0) * 1000
                if chunk.get("done"):
                    final_stats = chunk
                    break
    except Exception as e:
        return {"model": model, "ok": False, "error": str(e)}

    total_s = time.perf_counter() - t0
    eval_count = final_stats.get("eval_count", 0)
    eval_ns = final_stats.get("eval_duration", 0)
    tok_s = (eval_count / (eval_ns / 1e9)) if eval_ns > 0 else 0.0
    gpu = get_gpu()
    return {
        "model": model,
        "ok": True,
        "ttft_ms": round(ttft_ms or (total_s * 1000), 1),
        "total_s": round(total_s, 2),
        "eval_tokens": eval_count,
        "tok_per_s": round(tok_s, 2),
        "vram_used_mib": gpu.get("vram_used_mib"),
    }


def measure_opencode_cli_ms() -> dict:
    results = {}
    for label, cmd in [
        ("version_ms", ["opencode", "--version"]),
        ("debug_agents_ms", ["opencode", "debug", "agents"]),
    ]:
        t0 = time.perf_counter()
        res = subprocess.run(cmd, capture_output=True, timeout=15, check=False)
        elapsed = (time.perf_counter() - t0) * 1000
        results[label] = round(elapsed, 1) if res.returncode == 0 else None
    return results


def main():
    parser = argparse.ArgumentParser(description="OpenCode-Saghet Ollama & CUDA Benchmark")
    parser.add_argument("--models", nargs="*", default=["qwen3.5:4b", "qwen3.5:9b", "qwen2.5-coder:7b", "abliterant/qwen3.5-rana:9b"])
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    installed = list_ollama_models()
    gpu_before = get_gpu()
    ram_before = get_ram_mib()
    cli_perf = measure_opencode_cli_ms()

    prompt = "Escribe una función Python `is_even(n: int) -> bool` en una sola línea."
    bench_results = []
    for m in args.models:
        resolved = resolve_model_with_fallback(m, installed)
        bench_results.append(bench_model(resolved, prompt))

    report = {
        "gpu": gpu_before,
        "ram_mib": ram_before,
        "opencode_cli": cli_perf,
        "installed_models_count": len(installed),
        "fallback_test": resolve_model_with_fallback("nonexistent-model:latest", installed),
        "benchmarks": bench_results,
    }

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
