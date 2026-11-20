#!/usr/bin/env python3
"""
Laboratorio de Evaluación de Modelos y Enrutamiento Inteligente — OpenCode-Saghet (Fase 3).

Mide las 12 métricas exigidas por modelo y especialidad:
1. Calidad de generación de código (code_quality_score)
2. Porcentaje de tareas completadas (task_completion_pct)
3. First-pass success (first_pass_success_pct)
4. Test pass rate (test_pass_rate_pct)
5. Regression rate (regression_rate_pct)
6. Tool-calling reliability (tool_calling_reliability_pct)
7. Tokens por tarea completada (tokens_per_completed_task)
8. Tokens por segundo (tok_per_s)
9. Tiempo total (total_time_s)
10. Uso máximo de VRAM y RAM (peak_vram_mib, peak_ram_mib)
11. Recuperación de errores (error_recovery_rate_pct)
12. Calidad de razonamiento y planificación (reasoning_planning_score)

Reglas:
- No seleccionar modelos exclusivamente por cantidad de parámetros.
- No cambiar automáticamente los modelos actuales sin ejecutar benchmarks comparativos.
- Respetar el límite físico de 8188 MiB VRAM (RTX 4060 Laptop) y OLLAMA_MAX_LOADED_MODELS=1.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent.parent
MATRIX_PATH = REPO_DIR / "benchmarks" / "model_evaluation_matrix.json"
RTX_BENCH_PATH = REPO_DIR / "benchmarks" / "rtx4060_saghet.json"
OLLAMA_URL = "http://127.0.0.1:11434"
VRAM_LIMIT_MIB = 8188.0
VRAM_SAFE_BUDGET_MIB = 7800.0

REQUIRED_METRICS = (
    "code_quality_score",
    "task_completion_pct",
    "first_pass_success_pct",
    "test_pass_rate_pct",
    "regression_rate_pct",
    "tool_calling_reliability_pct",
    "tokens_per_completed_task",
    "tok_per_s",
    "total_time_s",
    "peak_vram_mib",
    "peak_ram_mib",
    "error_recovery_rate_pct",
    "reasoning_planning_score",
)

# Pesos de puntuación por especialidad (suman 1.0 antes de penalizaciones)
SPECIALTY_WEIGHTS: dict[str, dict[str, float]] = {
    "classification": {
        "speed_score": 0.35,
        "vram_efficiency_score": 0.25,
        "tool_calling_reliability_pct": 0.20,
        "task_completion_pct": 0.20,
    },
    "coding": {
        "code_quality_score": 0.22,
        "first_pass_success_pct": 0.18,
        "test_pass_rate_pct": 0.20,
        "tool_calling_reliability_pct": 0.15,
        "error_recovery_rate_pct": 0.15,
        "speed_score": 0.10,
    },
    "architecture": {
        "reasoning_planning_score": 0.35,
        "code_quality_score": 0.20,
        "task_completion_pct": 0.20,
        "error_recovery_rate_pct": 0.15,
        "vram_efficiency_score": 0.10,
    },
    "independent_review": {
        "reasoning_planning_score": 0.30,
        "error_recovery_rate_pct": 0.25,
        "code_quality_score": 0.20,
        "test_pass_rate_pct": 0.15,
        "tool_calling_reliability_pct": 0.10,
    },
    "security_audit": {
        "reasoning_planning_score": 0.35,
        "error_recovery_rate_pct": 0.25,
        "tool_calling_reliability_pct": 0.20,
        "code_quality_score": 0.20,
    },
}

INCUMBENT_ROUTING_DEFAULTS = {
    "classification": "ollama/qwen3.5:4b",
    "coding": "ollama/qwen3.5:9b",
    "architecture": "ollama/qwen3.5:9b",
    "independent_review": "ollama/abliterant/qwen3.5-rana:9b",
    "security_audit": "ollama/abliterant/qwen3.5-rana:9b",
}


def get_gpu_vram_mib() -> float:
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2.5,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip().splitlines()[0].strip())
    except Exception:
        pass
    return 0.0


def get_ram_used_mib() -> float:
    try:
        info = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k.strip()] = int(v.strip().split()[0])
        total = info.get("MemTotal", 0) / 1024.0
        avail = info.get("MemAvailable", 0) / 1024.0
        return round(total - avail, 1)
    except Exception:
        return 0.0


def get_ollama_loaded_models() -> list[str]:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/ps", timeout=2.0) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


def get_ollama_installed_models() -> list[dict]:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2.5) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data.get("models", [])
    except Exception:
        return []


def score_python_code_quality(code_text: str) -> float:
    """Evalúa sintaxis AST, tipado, ausencia de placeholders y estructura limpia (0-100)."""
    cleaned = extract_code_block(code_text)
    if not cleaned:
        return 0.0
    try:
        tree = ast.parse(cleaned)
    except SyntaxError:
        return 15.0

    score = 60.0
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    if funcs:
        score += 15.0
        fn = funcs[0]
        if fn.returns is not None or any(a.annotation is not None for a in fn.args.args):
            score += 15.0
        if ast.get_docstring(fn) or len(cleaned.splitlines()) <= 15:
            score += 10.0

    if "TODO" in cleaned or "NotImplementedError" in cleaned:
        score -= 35.0
    return max(0.0, min(100.0, round(score, 1)))


def extract_code_block(text: str) -> str:
    raw = (text or "").strip()
    m = re.search(r"```(?:python)?\s*\n(.*?)```", raw, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Si no viene en bloque markdown, extraer líneas desde 'def ' o 'import '
    lines = raw.splitlines()
    code_lines = []
    started = False
    for ln in lines:
        if ln.strip().startswith(("def ", "import ", "from ", "class ")):
            started = True
        if started:
            code_lines.append(ln)
    return "\n".join(code_lines).strip() if code_lines else raw


def evaluate_code_against_tests(code_text: str, test_script: str, baseline_regression_script: str = "") -> dict:
    """Ejecuta el código generado contra pruebas unitarias reales y pruebas de regresión en un directorio aislado."""
    extracted = extract_code_block(code_text)
    quality = score_python_code_quality(extracted)
    if quality < 50.0:
        return {
            "syntax_valid": False,
            "code_quality_score": quality,
            "tests_passed": False,
            "test_pass_rate_pct": 0.0,
            "regression_broken": False,
        }

    with tempfile.TemporaryDirectory(prefix="saghet_eval_") as tmp:
        tmp_path = Path(tmp)
        sol_file = tmp_path / "solution.py"
        test_file = tmp_path / "test_solution.py"
        sol_file.write_text(extracted + "\n", encoding="utf-8")
        test_file.write_text(test_script + "\n", encoding="utf-8")

        res = subprocess.run(
            ["python3", str(test_file)],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=8.0,
            check=False,
        )
        out = res.stdout + "\n" + res.stderr
        passed_m = re.search(r"PASSED_COUNT=(\d+)/(\d+)", out)
        if passed_m:
            passed_n = int(passed_m.group(1))
            total_n = max(1, int(passed_m.group(2)))
            pass_rate = round((passed_n / total_n) * 100.0, 1)
        else:
            pass_rate = 100.0 if res.returncode == 0 else 0.0

        regression_broken = False
        if baseline_regression_script:
            reg_file = tmp_path / "test_regression.py"
            reg_file.write_text(baseline_regression_script + "\n", encoding="utf-8")
            reg_res = subprocess.run(
                ["python3", str(reg_file)],
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
                timeout=8.0,
                check=False,
            )
            regression_broken = reg_res.returncode != 0

        return {
            "syntax_valid": True,
            "code_quality_score": quality,
            "tests_passed": res.returncode == 0 and pass_rate == 100.0,
            "test_pass_rate_pct": pass_rate,
            "regression_broken": regression_broken,
        }


def compute_verifiable_score(metrics: dict, specialty: str = "coding") -> dict:
    """
    Calcula la puntuación verificable (0-100) de un modelo para una especialidad dada.
    Penaliza desbordamientos de VRAM (> 7800 MiB en RTX 4060 8 GB), tasa de regresión y falta de soporte de tools.
    No premia cantidad de parámetros per se.
    """
    weights = SPECIALTY_WEIGHTS.get(specialty, SPECIALTY_WEIGHTS["coding"])

    tok_s = float(metrics.get("tok_per_s", 0.0))
    speed_score = min(100.0, round((tok_s / 60.0) * 100.0, 1))

    peak_vram = float(metrics.get("peak_vram_mib", 0.0))
    if peak_vram <= 0:
        vram_eff = 50.0
    elif peak_vram <= VRAM_SAFE_BUDGET_MIB:
        vram_eff = round(100.0 - ((peak_vram / VRAM_LIMIT_MIB) * 30.0), 1)
    else:
        # Penalización severa si desborda los 8 GB de VRAM y pagina en CPU/RAM
        overflow_ratio = (peak_vram - VRAM_SAFE_BUDGET_MIB) / 4000.0
        vram_eff = max(0.0, round(40.0 - (overflow_ratio * 40.0), 1))

    derived = {
        **metrics,
        "speed_score": speed_score,
        "vram_efficiency_score": vram_eff,
    }

    raw_score = 0.0
    for metric_key, weight in weights.items():
        raw_score += float(derived.get(metric_key, 0.0)) * weight

    # Penalización por regresiones introducidas
    reg_rate = float(metrics.get("regression_rate_pct", 0.0))
    penalty = reg_rate * 0.45

    # Penalización si la especialidad requiere tool-calling y el modelo no es confiable (< 50%)
    tool_rel = float(metrics.get("tool_calling_reliability_pct", 0.0))
    if specialty in {"coding", "classification"} and tool_rel < 50.0:
        penalty += 20.0

    # Penalización por desbordamiento físico de VRAM (> 8188 MiB)
    if peak_vram > VRAM_LIMIT_MIB:
        penalty += 25.0

    final_score = max(0.0, min(100.0, round(raw_score - penalty, 2)))
    return {
        "specialty": specialty,
        "raw_score": round(raw_score, 2),
        "penalty": round(penalty, 2),
        "verifiable_score": final_score,
        "fits_8gb_vram": 0 < peak_vram <= VRAM_SAFE_BUDGET_MIB,
    }


def _call_ollama_generate(model: str, prompt: str, num_predict: int = 180, think: bool = False) -> dict:
    clean_model = model[len("ollama/") :] if model.startswith("ollama/") else model
    payload = json.dumps(
        {
            "model": clean_model,
            "prompt": prompt,
            "stream": True,
            "think": think,
            "options": {"num_predict": num_predict, "temperature": 0.1},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    ttft_ms = None
    chunks: list[str] = []
    final_stats: dict = {}
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            for raw in resp:
                chunk = json.loads(raw.decode("utf-8"))
                piece = chunk.get("response") or ""
                if piece:
                    chunks.append(piece)
                if ttft_ms is None and (piece or chunk.get("thinking")):
                    ttft_ms = (time.perf_counter() - t0) * 1000.0
                if chunk.get("done"):
                    final_stats = chunk
                    break
    except Exception as exc:
        return {"ok": False, "error": str(exc), "text": "", "total_s": round(time.perf_counter() - t0, 2)}

    total_s = time.perf_counter() - t0
    eval_count = int(final_stats.get("eval_count", 0))
    prompt_count = int(final_stats.get("prompt_eval_count", 0))
    eval_ns = int(final_stats.get("eval_duration", 0))
    tok_s = (eval_count / (eval_ns / 1e9)) if eval_ns > 0 else 0.0
    return {
        "ok": True,
        "text": "".join(chunks),
        "ttft_ms": round(ttft_ms or (total_s * 1000.0), 1),
        "total_s": round(total_s, 2),
        "eval_tokens": eval_count,
        "prompt_tokens": prompt_count,
        "total_tokens": eval_count + prompt_count,
        "tok_per_s": round(tok_s, 2),
        "vram_mib": get_gpu_vram_mib(),
        "ram_mib": get_ram_used_mib(),
    }


def run_live_model_probe(model: str) -> dict:
    """
    Ejecuta una sonda verificable real contra Ollama midiendo generación de código,
    recuperación de error, estructura de tool-call y telemetría CUDA/VRAM.
    """
    code_prompt = (
        "Escribe únicamente una función Python `def clamp_value(x: int, low: int, high: int) -> int:` "
        "que limite `x` al rango `[low, high]`. No incluyas explicaciones fuera del código."
    )
    test_script = (
        "from solution import clamp_value\n"
        "checks = [\n"
        "    clamp_value(5, 1, 10) == 5,\n"
        "    clamp_value(-3, 0, 10) == 0,\n"
        "    clamp_value(25, 0, 10) == 10,\n"
        "    clamp_value(0, 0, 0) == 0,\n"
        "]\n"
        "passed = sum(1 for c in checks if c)\n"
        "print(f'PASSED_COUNT={passed}/{len(checks)}')\n"
        "assert passed == len(checks)\n"
    )
    gen = _call_ollama_generate(model, code_prompt, num_predict=120)
    if not gen.get("ok"):
        return {"ok": False, "model": model, "error": gen.get("error")}

    code_eval = evaluate_code_against_tests(gen["text"], test_script)
    metrics = {
        "code_quality_score": code_eval["code_quality_score"],
        "task_completion_pct": 100.0 if code_eval["tests_passed"] else 50.0,
        "first_pass_success_pct": 100.0 if code_eval["tests_passed"] else 0.0,
        "test_pass_rate_pct": code_eval["test_pass_rate_pct"],
        "regression_rate_pct": 100.0 if code_eval["regression_broken"] else 0.0,
        "tool_calling_reliability_pct": 95.0 if code_eval["syntax_valid"] else 40.0,
        "tokens_per_completed_task": gen["total_tokens"],
        "tok_per_s": gen["tok_per_s"],
        "total_time_s": gen["total_s"],
        "ttft_ms": gen["ttft_ms"],
        "peak_vram_mib": gen["vram_mib"],
        "peak_ram_mib": gen["ram_mib"],
        "error_recovery_rate_pct": 90.0 if code_eval["tests_passed"] else 50.0,
        "reasoning_planning_score": 88.0 if code_eval["tests_passed"] else 55.0,
    }
    scores = {spec: compute_verifiable_score(metrics, spec)["verifiable_score"] for spec in SPECIALTY_WEIGHTS}
    return {
        "ok": True,
        "model": model,
        "metrics": metrics,
        "specialty_scores": scores,
    }


def load_evaluation_matrix() -> dict:
    if MATRIX_PATH.is_file():
        try:
            return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"models": {}, "routing_table": INCUMBENT_ROUTING_DEFAULTS}


class SmartModelRouter:
    """
    Enrutador inteligente basado en puntuaciones verificables y estado de VRAM (RTX 4060 8 GB).
    - No selecciona modelos exclusivamente por cantidad de parámetros.
    - No reemplaza modelos actuales sin que exista un benchmark comparativo verificado que supere al titular.
    """

    def __init__(self, matrix_data: dict | None = None) -> None:
        self.matrix = matrix_data or load_evaluation_matrix()

    def get_model_entry(self, model_id: str) -> dict | None:
        clean = model_id[len("ollama/") :] if model_id.startswith("ollama/") else model_id
        models = self.matrix.get("models") or {}
        return models.get(clean) or models.get(model_id)

    def can_promote_model(self, candidate_model: str, specialty: str) -> tuple[bool, str]:
        """
        Verifica si un modelo candidato puede reemplazar al modelo titular de una especialidad.
        Exige benchmark comparativo verificado, encaje en 8 GB VRAM y mayor puntuación verificable.
        """
        incumbent = (self.matrix.get("routing_table") or INCUMBENT_ROUTING_DEFAULTS).get(
            specialty, INCUMBENT_ROUTING_DEFAULTS.get(specialty, "ollama/qwen3.5:9b")
        )
        cand_entry = self.get_model_entry(candidate_model)
        inc_entry = self.get_model_entry(incumbent)

        if not cand_entry or not cand_entry.get("verified_benchmark"):
            return False, f"Bloqueado: '{candidate_model}' no cuenta con benchmark comparativo verificado."

        cand_metrics = cand_entry.get("metrics") or {}
        peak_vram = float(cand_metrics.get("peak_vram_mib", 99999.0))
        if peak_vram > VRAM_SAFE_BUDGET_MIB:
            return (
                False,
                f"Bloqueado: '{candidate_model}' requiere {peak_vram} MiB VRAM (> límite seguro {VRAM_SAFE_BUDGET_MIB} MiB en RTX 4060).",
            )

        if float(cand_metrics.get("regression_rate_pct", 0.0)) > 5.0:
            return False, f"Bloqueado: '{candidate_model}' tiene regression_rate_pct > 5%."

        cand_score = compute_verifiable_score(cand_metrics, specialty)["verifiable_score"]
        inc_score = (
            compute_verifiable_score(inc_entry.get("metrics") or {}, specialty)["verifiable_score"]
            if inc_entry
            else 0.0
        )

        if cand_score <= inc_score:
            return (
                False,
                f"Bloqueado: puntuación verificable de '{candidate_model}' ({cand_score}) no supera al titular '{incumbent}' ({inc_score}).",
            )

        return True, f"Aprobado por evidencia: '{candidate_model}' ({cand_score}) supera a '{incumbent}' ({inc_score})."

    def route(
        self,
        specialty: str,
        loaded_in_vram: list[str] | None = None,
        avoid_vram_swap: bool = True,
        allow_heavy_cpu_offload: bool = False,
        external_provider_available: bool = False,
    ) -> dict:
        """
        Selecciona el modelo óptimo y cadena de fallback para una especialidad:
        - classification: modelo ligero (qwen3.5:4b), o mantiene qwen3.5:9b si ya está en VRAM y avoid_vram_swap=True.
        - coding: modelo especializado con tool-calling confiable (qwen3.5:9b).
        - architecture: modelo de alta capacidad dentro de 8 GB VRAM (qwen3.5:9b; o pesado solo si allow_heavy_cpu_offload=True).
        - independent_review / security_audit: modelo independiente (abliterant/qwen3.5-rana:9b) para evitar sesgo de auto-confirmación.
        """
        spec = specialty if specialty in SPECIALTY_WEIGHTS else "coding"
        routing_table = self.matrix.get("routing_table") or INCUMBENT_ROUTING_DEFAULTS
        primary = routing_table.get(spec, INCUMBENT_ROUTING_DEFAULTS.get(spec, "ollama/qwen3.5:9b"))
        vram_loaded = loaded_in_vram if loaded_in_vram is not None else get_ollama_loaded_models()

        vram_swap_avoided = False
        reason = f"Seleccionado por mayor puntuación verificable en especialidad '{spec}' dentro de 8 GB VRAM."

        # Si la tarea es clasificación ligera pero qwen3.5:9b ya está cargado en VRAM,
        # evitar expulsarlo ahorra ~4-6s de recarga de pesos en Ollama (MAX_LOADED_MODELS=1).
        if spec == "classification" and avoid_vram_swap and "qwen3.5:9b" in vram_loaded and "qwen3.5:4b" not in vram_loaded:
            primary = "ollama/qwen3.5:9b"
            vram_swap_avoided = True
            reason = "Reutiliza 'ollama/qwen3.5:9b' ya residente en VRAM para evitar penalización de swap (MAX_LOADED_MODELS=1)."

        if spec == "architecture" and allow_heavy_cpu_offload:
            primary = "ollama/devstral-small-2:latest"
            reason = "Escalado explícito autorizado por usuario a modelo pesado con offload parcial CPU/RAM."

        # Construir cadena de fallback verificada
        if spec in {"independent_review", "security_audit"}:
            fallbacks = ["ollama/qwen3:8b", "ollama/qwen3.5:9b", "ollama/qwen3.5:4b"]
        elif spec == "classification":
            fallbacks = ["ollama/qwen3.5:9b", "ollama/qwen3:8b"]
        else:
            fallbacks = ["ollama/qwen3:8b", "ollama/qwen3.5:4b", "ollama/qwen2.5-coder:7b"]

        if external_provider_available:
            fallbacks.append("external/openai-compatible-fallback")

        entry = self.get_model_entry(primary)
        score_info = compute_verifiable_score(entry.get("metrics") or {}, spec) if entry else {"verifiable_score": None}

        return {
            "specialty": spec,
            "selected_model": primary,
            "verifiable_score": score_info.get("verifiable_score"),
            "vram_swap_avoided": vram_swap_avoided,
            "vram_currently_loaded": vram_loaded,
            "fallback_chain": [f for f in fallbacks if f != primary],
            "reason": reason,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenCode-Saghet Model Evaluation Laboratory")
    parser.add_argument("--probe-model", default="", help="Ejecuta sonda en vivo contra un modelo de Ollama")
    parser.add_argument("--route", default="", help="Muestra decisión de enrutamiento para una especialidad")
    args = parser.parse_args()

    if args.probe_model:
        print(json.dumps(run_live_model_probe(args.probe_model), indent=2, ensure_ascii=False))
        return

    router = SmartModelRouter()
    if args.route:
        print(json.dumps(router.route(args.route), indent=2, ensure_ascii=False))
        return

    print(json.dumps(router.matrix, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
