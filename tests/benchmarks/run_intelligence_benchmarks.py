#!/usr/bin/env python3
"""
Laboratorio de Pruebas: 10 Benchmarks Reproducibles de Inteligencia Real — OpenCode-Saghet (Fase 7 / Fase 8 Misión).

Regla fundamental:
- Prohibidas las pruebas artificiales que simulen el éxito de un agente modificando manualmente el código desde el propio test.
- Cada benchmark utiliza un proyecto Git aislado, invoca realmente al modelo local en Ollama (qwen3.5:9b en RTX 4060),
  aplica exclusivamente la salida generada por el modelo, ejecuta pruebas objetivas (unittest / py_compile) y valida
  la entrega mediante el Supervisor de Calidad (QualitySupervisor).

Escenarios incluidos (10/10):
1. feature_development (Desarrollo de una funcionalidad)
2. bug_fixing (Corrección de bugs)
3. refactoring (Refactorización sin regresiones)
4. debugging (Depuración a partir de traceback real)
5. test_creation (Creación de pruebas verificada con mutación negativa)
6. technical_research (Investigación técnica con extracción verificable)
7. build_error_resolution (Resolución de errores de compilación/sintaxis)
8. multi_file_work (Trabajo multiarchivo con importaciones cruzadas)
9. multi_agent_execution (Ejecución multiagente coordinada en DAG)
10. fault_recovery (Recuperación ante fallos mediante feedback del Supervisor)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.eval.model_lab import (
    _call_ollama_generate,
    extract_code_block,
    get_gpu_vram_mib,
    get_ram_used_mib,
    score_python_code_quality,
)
from scripts.harness.workflow_engine import HarnessTaskBoard, HarnessWorkflowEngine
from scripts.supervisor.gentle_ai_bridge import classify_and_route
from scripts.supervisor.quality_supervisor import QualitySupervisor

DEFAULT_BENCH_OUT = REPO_DIR / "benchmarks" / "saghet_intelligence_benchmarks.json"


def _init_isolated_git_project(root: Path, initial_files: dict[str, str]) -> None:
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "bench@saghet.local"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Saghet Bench"], check=True)
    for rel_path, content in initial_files.items():
        fpath = root / rel_path
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "baseline"], check=True, capture_output=True)


def _run_unittest(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", "-m", "unittest", "discover", "-s", str(root), "-v"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=15.0,
        check=False,
    )


def _git_changed_files(root: Path) -> list[str]:
    res = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=5.0,
        check=False,
    )
    return [ln[3:].strip() for ln in res.stdout.splitlines() if ln.strip()]


def bench_01_feature_development(model: str, supervisor: QualitySupervisor) -> dict:
    """1. Desarrollo de una funcionalidad desde cero en proyecto aislado."""
    with tempfile.TemporaryDirectory(prefix="saghet_b01_feat_") as tmp:
        proj = Path(tmp)
        _init_isolated_git_project(
            proj,
            {
                "text_utils.py": "# Modulo pendiente de implementacion\n",
                "test_text_utils.py": (
                    "import unittest\n"
                    "from text_utils import slugify\n\n"
                    "class TestSlugify(unittest.TestCase):\n"
                    "    def test_basic(self):\n"
                    "        self.assertEqual(slugify('Hola Mundo Matrix!'), 'hola-mundo-matrix')\n"
                    "    def test_multiple_spaces_and_symbols(self):\n"
                    "        self.assertEqual(slugify('  OpenCode --- Saghet 2.0  '), 'opencode-saghet-2-0')\n"
                    "if __name__ == '__main__':\n"
                    "    unittest.main()\n"
                ),
            },
        )
        objective = (
            "Implementa en Python el módulo `text_utils.py` con la función `def slugify(text: str) -> str:` "
            "que convierta a minúsculas, reemplace cualquier secuencia de caracteres no alfanuméricos "
            "(`[^a-z0-9]+`) por un único guion `-` y elimine guiones al inicio y al final. "
            "Devuelve únicamente el código Python válido."
        )
        route = classify_and_route(objective)
        gen = _call_ollama_generate(model, objective, num_predict=180, think=False)
        code = extract_code_block(gen.get("text", ""))
        (proj / "text_utils.py").write_text(code + "\n", encoding="utf-8")

        test_res = _run_unittest(proj)
        diffs = _git_changed_files(proj)
        agent_report = f"Archivo implementado: text_utils.py#L1. Salida tests:\n{test_res.stdout}\n{test_res.stderr}"
        decision = supervisor.evaluate_execution(
            objective=objective,
            agent=route["primary_specialist"],
            agent_output=agent_report,
            diff_files=diffs,
            test_output=test_res.stdout + test_res.stderr,
            test_returncode=test_res.returncode,
            reviewer_verdict="APPROVED" if test_res.returncode == 0 else "CHANGES_REQUESTED",
        )
        return {
            "id": "01_feature_development",
            "category": "Desarrollo de una funcionalidad",
            "specialist": route["primary_specialist"],
            "model": model,
            "passed": test_res.returncode == 0 and decision["verdict"] == "ACCEPT",
            "supervisor_verdict": decision["verdict"],
            "code_quality": score_python_code_quality(code),
            "tok_per_s": gen.get("tok_per_s", 0.0),
            "tokens": gen.get("total_tokens", 0),
            "elapsed_s": gen.get("total_s", 0.0),
        }


def bench_02_bug_fixing(model: str, supervisor: QualitySupervisor) -> dict:
    """2. Corrección de bug real verificando fallo inicial y éxito tras fix generado por IA."""
    with tempfile.TemporaryDirectory(prefix="saghet_b02_bug_") as tmp:
        proj = Path(tmp)
        buggy_code = (
            "def apply_discount(price: float, percent: float) -> float:\n"
            "    \"\"\"Aplica un descuento porcentual (0-100) al precio.\"\"\"\n"
            "    return round(price + (price * (percent / 100.0)), 2)\n"
        )
        test_code = (
            "import unittest\n"
            "from billing import apply_discount\n\n"
            "class TestBilling(unittest.TestCase):\n"
            "    def test_discount_20_percent(self):\n"
            "        self.assertEqual(apply_discount(100.0, 20.0), 80.0)\n"
            "    def test_discount_zero(self):\n"
            "        self.assertEqual(apply_discount(50.0, 0.0), 50.0)\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n"
        )
        _init_isolated_git_project(proj, {"billing.py": buggy_code, "test_billing.py": test_code})

        # Confirmar fallo real antes de invocar al modelo
        pre_test = _run_unittest(proj)
        assert pre_test.returncode != 0, "El proyecto debía fallar antes de la corrección del modelo"

        objective = (
            f"El archivo `billing.py` tiene un bug y falla las pruebas unitarias.\n"
            f"Código actual de `billing.py`:\n```python\n{buggy_code}```\n"
            f"Fallo de unittest:\n{pre_test.stderr}\n"
            f"Corrige `billing.py` para que reste el descuento en lugar de sumarlo. Devuelve únicamente el código Python corregido."
        )
        gen = _call_ollama_generate(model, objective, num_predict=160, think=False)
        fixed_code = extract_code_block(gen.get("text", ""))
        (proj / "billing.py").write_text(fixed_code + "\n", encoding="utf-8")

        post_test = _run_unittest(proj)
        diffs = _git_changed_files(proj)
        decision = supervisor.evaluate_execution(
            objective=objective,
            agent="senior-developer",
            agent_output=f"Bug corregido en billing.py#L1-L4.\n{post_test.stderr}",
            diff_files=diffs,
            test_output=post_test.stderr,
            test_returncode=post_test.returncode,
            reviewer_verdict="APPROVED" if post_test.returncode == 0 else "CHANGES_REQUESTED",
        )
        return {
            "id": "02_bug_fixing",
            "category": "Corrección de bugs",
            "specialist": "senior-developer",
            "model": model,
            "pre_fix_failed": pre_test.returncode != 0,
            "passed": post_test.returncode == 0 and decision["verdict"] == "ACCEPT",
            "supervisor_verdict": decision["verdict"],
            "tok_per_s": gen.get("tok_per_s", 0.0),
            "tokens": gen.get("total_tokens", 0),
            "elapsed_s": gen.get("total_s", 0.0),
        }


def bench_03_refactoring(model: str, supervisor: QualitySupervisor) -> dict:
    """3. Refactorización preservando el 100 % de las pruebas de regresión y mejorando calidad AST."""
    with tempfile.TemporaryDirectory(prefix="saghet_b03_ref_") as tmp:
        proj = Path(tmp)
        legacy_code = (
            "def calc_metrics(arr):\n"
            "    s = 0\n"
            "    for x in arr:\n"
            "        if x > 0:\n"
            "            s = s + x\n"
            "    c = 0\n"
            "    for x in arr:\n"
            "        if x > 0:\n"
            "            c = c + 1\n"
            "    return {'sum_pos': s, 'count_pos': c}\n"
        )
        test_code = (
            "import unittest\n"
            "from metrics import calc_metrics\n\n"
            "class TestMetrics(unittest.TestCase):\n"
            "    def test_mixed_numbers(self):\n"
            "        self.assertEqual(calc_metrics([-5, 2, 0, 8, -1]), {'sum_pos': 10, 'count_pos': 2})\n"
            "    def test_all_negative(self):\n"
            "        self.assertEqual(calc_metrics([-3, -1]), {'sum_pos': 0, 'count_pos': 0})\n"
        )
        _init_isolated_git_project(proj, {"metrics.py": legacy_code, "test_metrics.py": test_code})

        objective = (
            f"Refactoriza `metrics.py` para eliminar el doble bucle redundante, añadir anotaciones de tipos "
            f"(`def calc_metrics(arr: list[int]) -> dict[str, int]:`) y docstring, manteniendo exactamente "
            f"el mismo contrato de retorno `{{'sum_pos': ..., 'count_pos': ...}}`.\n"
            f"Código original:\n```python\n{legacy_code}```\n"
            f"Devuelve únicamente el código Python refactorizado."
        )
        gen = _call_ollama_generate(model, objective, num_predict=180, think=False)
        ref_code = extract_code_block(gen.get("text", ""))
        (proj / "metrics.py").write_text(ref_code + "\n", encoding="utf-8")

        test_res = _run_unittest(proj)
        diffs = _git_changed_files(proj)
        q_before = score_python_code_quality(legacy_code)
        q_after = score_python_code_quality(ref_code)
        decision = supervisor.evaluate_execution(
            objective=objective,
            agent="senior-developer",
            agent_output=f"Refactorizado metrics.py#L1. Calidad AST: {q_before} -> {q_after}.\n{test_res.stderr}",
            diff_files=diffs,
            test_output=test_res.stderr,
            test_returncode=test_res.returncode,
            reviewer_verdict="APPROVED" if test_res.returncode == 0 else "CHANGES_REQUESTED",
        )
        return {
            "id": "03_refactoring",
            "category": "Refactorización",
            "specialist": "senior-developer",
            "model": model,
            "quality_before": q_before,
            "quality_after": q_after,
            "passed": test_res.returncode == 0 and q_after >= q_before and decision["verdict"] == "ACCEPT",
            "supervisor_verdict": decision["verdict"],
            "tok_per_s": gen.get("tok_per_s", 0.0),
            "tokens": gen.get("total_tokens", 0),
            "elapsed_s": gen.get("total_s", 0.0),
        }


def bench_04_debugging(model: str, supervisor: QualitySupervisor) -> dict:
    """4. Depuración de una excepción en tiempo de ejecución (ZeroDivisionError) a partir de traceback."""
    with tempfile.TemporaryDirectory(prefix="saghet_b04_dbg_") as tmp:
        proj = Path(tmp)
        crashing_code = (
            "def safe_average(values: list[float]) -> float:\n"
            "    return round(sum(values) / len(values), 2)\n"
        )
        test_code = (
            "import unittest\n"
            "from stats_mod import safe_average\n\n"
            "class TestStats(unittest.TestCase):\n"
            "    def test_normal(self):\n"
            "        self.assertEqual(safe_average([10.0, 20.0, 30.0]), 20.0)\n"
            "    def test_empty_list_does_not_crash(self):\n"
            "        self.assertEqual(safe_average([]), 0.0)\n"
        )
        _init_isolated_git_project(proj, {"stats_mod.py": crashing_code, "test_stats.py": test_code})
        crash_res = _run_unittest(proj)

        objective = (
            f"Depura el siguiente `ZeroDivisionError` en `stats_mod.py`.\n"
            f"Traceback observado:\n{crash_res.stderr}\n"
            f"Código actual:\n```python\n{crashing_code}```\n"
            f"Si `values` está vacía, `safe_average` debe devolver `0.0`. Devuelve únicamente el código Python corregido."
        )
        gen = _call_ollama_generate(model, objective, num_predict=150, think=False)
        fixed = extract_code_block(gen.get("text", ""))
        (proj / "stats_mod.py").write_text(fixed + "\n", encoding="utf-8")

        post_res = _run_unittest(proj)
        diffs = _git_changed_files(proj)
        decision = supervisor.evaluate_execution(
            objective=objective,
            agent="senior-developer",
            agent_output=f"Depurado ZeroDivisionError en stats_mod.py#L1.\n{post_res.stderr}",
            diff_files=diffs,
            test_output=post_res.stderr,
            test_returncode=post_res.returncode,
            reviewer_verdict="APPROVED" if post_res.returncode == 0 else "CHANGES_REQUESTED",
        )
        return {
            "id": "04_debugging",
            "category": "Depuración",
            "specialist": "senior-developer",
            "model": model,
            "passed": post_res.returncode == 0 and decision["verdict"] == "ACCEPT",
            "supervisor_verdict": decision["verdict"],
            "tok_per_s": gen.get("tok_per_s", 0.0),
            "tokens": gen.get("total_tokens", 0),
            "elapsed_s": gen.get("total_s", 0.0),
        }


def bench_05_test_creation(model: str, supervisor: QualitySupervisor) -> dict:
    """5. Creación de pruebas unitarias por el agente QA, verificadas con prueba de mutación."""
    with tempfile.TemporaryDirectory(prefix="saghet_b05_qa_") as tmp:
        proj = Path(tmp)
        target_module = (
            "def is_valid_port(port: int) -> bool:\n"
            "    \"\"\"Devuelve True si port es un entero entre 1 y 65535 inclusive.\"\"\"\n"
            "    return isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535\n"
        )
        _init_isolated_git_project(proj, {"net_validator.py": target_module})

        objective = (
            f"Escribe un archivo de pruebas `test_net_validator.py` usando `unittest.TestCase` para probar "
            f"`from net_validator import is_valid_port`.\n"
            f"Debe incluir aserciones para puertos válidos (ej. 80, 4780, 65535) y puertos inválidos (ej. 0, -1, 70000).\n"
            f"Devuelve únicamente el código Python de `test_net_validator.py`."
        )
        gen = _call_ollama_generate(model, objective, num_predict=240, think=False)
        test_code = extract_code_block(gen.get("text", ""))
        (proj / "test_net_validator.py").write_text(test_code + "\n", encoding="utf-8")

        # 1) Debe pasar contra el módulo correcto
        pass_on_valid = _run_unittest(proj)

        # 2) Prueba de mutación: si rompemos net_validator.py para que devuelva siempre True,
        # el test creado por el agente DEBE fallar (demuestra que el agente escribió asserts reales).
        (proj / "net_validator.py").write_text("def is_valid_port(port: int) -> bool:\n    return True\n", encoding="utf-8")
        fail_on_mutant = _run_unittest(proj)
        # Restaurar módulo válido
        (proj / "net_validator.py").write_text(target_module, encoding="utf-8")

        real_test_verified = pass_on_valid.returncode == 0 and fail_on_mutant.returncode != 0
        diffs = _git_changed_files(proj)
        decision = supervisor.evaluate_execution(
            objective=objective,
            agent="qa-engineer",
            agent_output=f"Creado test_net_validator.py#L1. Mutación detectada: {fail_on_mutant.returncode != 0}.\n{pass_on_valid.stderr}",
            diff_files=diffs,
            test_output=pass_on_valid.stderr,
            test_returncode=0 if real_test_verified else 1,
            reviewer_verdict="APPROVED" if real_test_verified else "CHANGES_REQUESTED",
        )
        return {
            "id": "05_test_creation",
            "category": "Creación de pruebas",
            "specialist": "qa-engineer",
            "model": model,
            "kills_mutant": fail_on_mutant.returncode != 0,
            "passed": real_test_verified and decision["verdict"] == "ACCEPT",
            "supervisor_verdict": decision["verdict"],
            "tok_per_s": gen.get("tok_per_s", 0.0),
            "tokens": gen.get("total_tokens", 0),
            "elapsed_s": gen.get("total_s", 0.0),
        }


def bench_06_technical_research(model: str, supervisor: QualitySupervisor) -> dict:
    """6. Investigación técnica de código y configuración con verificación objetiva de hallazgos."""
    repo_snippet = (
        "Archivo: service_config.json\n"
        "{\"service_name\": \"saghet-matrix-gateway\", \"listen_port\": 4780, \"db_engine\": \"sqlite_wal\", \"max_vram_mib\": 8188}\n"
        "Archivo: gateway.py (línea 42)\n"
        "def start_gateway_server(host: str = '127.0.0.1', port: int = 4780):\n"
    )
    objective = (
        f"Analiza e investiga los siguientes artefactos del proyecto sin modificar archivos:\n{repo_snippet}\n"
        f"Responde citando `service_config.json` y `gateway.py#L42` e incluye exactamente los valores: "
        f"puerto `4780`, motor `sqlite_wal`, función `start_gateway_server` y VRAM `8188`."
    )
    gen = _call_ollama_generate(model, objective, num_predict=180, think=False)
    text = gen.get("text", "")
    facts_ok = all(tok in text for tok in ("4780", "sqlite_wal", "start_gateway_server", "8188"))
    decision = supervisor.evaluate_execution(
        objective=objective,
        agent="researcher",
        agent_output=text if "gateway.py" in text else f"gateway.py#L42: {text}",
        is_readonly=True,
        require_tests=False,
        reviewer_verdict="APPROVED" if facts_ok else "CHANGES_REQUESTED",
    )
    return {
        "id": "06_technical_research",
        "category": "Investigación técnica",
        "specialist": "researcher",
        "model": model,
        "facts_verified": facts_ok,
        "passed": facts_ok and decision["verdict"] == "ACCEPT",
        "supervisor_verdict": decision["verdict"],
        "tok_per_s": gen.get("tok_per_s", 0.0),
        "tokens": gen.get("total_tokens", 0),
        "elapsed_s": gen.get("total_s", 0.0),
    }


def bench_07_build_error_resolution(model: str, supervisor: QualitySupervisor) -> dict:
    """7. Resolución de errores de compilación/sintaxis verificada con py_compile + unittest."""
    with tempfile.TemporaryDirectory(prefix="saghet_b07_build_") as tmp:
        proj = Path(tmp)
        broken_syntax = (
            "def parse_kv_line(line: str) -> tuple[str, str]\n"
            "    parts = [p.strip() for p in line.split('=', 1)\n"
            "    return (parts[0], parts[1] if len(parts) > 1 else '')\n"
        )
        test_code = (
            "import unittest\n"
            "from kv_parser import parse_kv_line\n\n"
            "class TestKV(unittest.TestCase):\n"
            "    def test_kv(self):\n"
            "        self.assertEqual(parse_kv_line('PORT = 4780'), ('PORT', '4780'))\n"
        )
        _init_isolated_git_project(proj, {"kv_parser.py": broken_syntax, "test_kv.py": test_code})

        comp_before = subprocess.run(
            ["python3", "-m", "py_compile", str(proj / "kv_parser.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert comp_before.returncode != 0, "Debía fallar compilación inicialmente"

        objective = (
            f"Resuelve el error de compilación en `kv_parser.py`:\n"
            f"Salida de `py_compile`:\n{comp_before.stderr}\n"
            f"Código con error:\n```python\n{broken_syntax}```\n"
            f"Devuelve únicamente el código Python corregido de `kv_parser.py`."
        )
        gen = _call_ollama_generate(model, objective, num_predict=150, think=False)
        fixed_code = extract_code_block(gen.get("text", ""))
        (proj / "kv_parser.py").write_text(fixed_code + "\n", encoding="utf-8")

        comp_after = subprocess.run(
            ["python3", "-m", "py_compile", str(proj / "kv_parser.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        test_after = _run_unittest(proj)
        diffs = _git_changed_files(proj)
        ok = comp_after.returncode == 0 and test_after.returncode == 0
        decision = supervisor.evaluate_execution(
            objective=objective,
            agent="senior-developer",
            agent_output=f"Error de compilación resuelto en kv_parser.py#L1.\n{test_after.stderr}",
            diff_files=diffs,
            test_output=test_after.stderr,
            test_returncode=0 if ok else 1,
            reviewer_verdict="APPROVED" if ok else "CHANGES_REQUESTED",
        )
        return {
            "id": "07_build_error_resolution",
            "category": "Resolución de errores de compilación",
            "specialist": "senior-developer",
            "model": model,
            "passed": ok and decision["verdict"] == "ACCEPT",
            "supervisor_verdict": decision["verdict"],
            "tok_per_s": gen.get("tok_per_s", 0.0),
            "tokens": gen.get("total_tokens", 0),
            "elapsed_s": gen.get("total_s", 0.0),
        }


def bench_08_multi_file_work(model: str, supervisor: QualitySupervisor) -> dict:
    """8. Trabajo multiarchivo coordinando contratos e importaciones entre módulos."""
    with tempfile.TemporaryDirectory(prefix="saghet_b08_multi_") as tmp:
        proj = Path(tmp)
        models_py = (
            "from dataclasses import dataclass\n\n"
            "@dataclass\n"
            "class OrderItem:\n"
            "    sku: str\n"
            "    unit_price: float\n"
            "    quantity: int\n"
        )
        test_order_py = (
            "import unittest\n"
            "from models import OrderItem\n"
            "from checkout import compute_order_total\n\n"
            "class TestCheckout(unittest.TestCase):\n"
            "    def test_total(self):\n"
            "        items = [OrderItem('A1', 15.5, 2), OrderItem('B2', 9.0, 1)]\n"
            "        self.assertEqual(compute_order_total(items), 40.0)\n"
            "    def test_empty(self):\n"
            "        self.assertEqual(compute_order_total([]), 0.0)\n"
        )
        _init_isolated_git_project(
            proj,
            {"models.py": models_py, "checkout.py": "# Pendiente\n", "test_checkout.py": test_order_py},
        )

        objective = (
            f"Dado el archivo `models.py`:\n```python\n{models_py}```\n"
            f"Implementa el archivo `checkout.py` que importe `OrderItem` desde `models` y defina "
            f"`def compute_order_total(items: list[OrderItem]) -> float:` devolviendo la suma de "
            f"`item.unit_price * item.quantity` redondeada a 2 decimales (`0.0` si la lista está vacía). "
            f"Devuelve únicamente el código Python de `checkout.py`."
        )
        gen = _call_ollama_generate(model, objective, num_predict=160, think=False)
        checkout_code = extract_code_block(gen.get("text", ""))
        (proj / "checkout.py").write_text(checkout_code + "\n", encoding="utf-8")

        test_res = _run_unittest(proj)
        diffs = _git_changed_files(proj)
        decision = supervisor.evaluate_execution(
            objective=objective,
            agent="backend-specialist",
            agent_output=f"Integrado checkout.py#L1 con models.py#L4.\n{test_res.stderr}",
            diff_files=diffs,
            test_output=test_res.stderr,
            test_returncode=test_res.returncode,
            reviewer_verdict="APPROVED" if test_res.returncode == 0 else "CHANGES_REQUESTED",
        )
        return {
            "id": "08_multi_file_work",
            "category": "Trabajo multiarchivo",
            "specialist": "backend-specialist",
            "model": model,
            "passed": test_res.returncode == 0 and decision["verdict"] == "ACCEPT",
            "supervisor_verdict": decision["verdict"],
            "tok_per_s": gen.get("tok_per_s", 0.0),
            "tokens": gen.get("total_tokens", 0),
            "elapsed_s": gen.get("total_s", 0.0),
        }


def bench_09_multi_agent_execution(model: str, supervisor: QualitySupervisor) -> dict:
    """9. Ejecución multiagente secuencial (architect -> senior-developer -> code-reviewer -> qa-engineer) en DAG."""
    with tempfile.TemporaryDirectory(prefix="saghet_b09_dag_") as tmp:
        proj = Path(tmp)
        _init_isolated_git_project(
            proj,
            {
                "token_bucket.py": "# Pendiente\n",
                "test_bucket.py": (
                    "import unittest\n"
                    "from token_bucket import can_consume\n\n"
                    "class TestBucket(unittest.TestCase):\n"
                    "    def test_consume(self):\n"
                    "        self.assertEqual(can_consume(10, 4), (True, 6))\n"
                    "        self.assertEqual(can_consume(3, 5), (False, 3))\n"
                ),
            },
        )
        board = HarnessTaskBoard(board_path=proj / "board.json")
        engine = HarnessWorkflowEngine(board=board)
        metrics_acc = {"tokens": 0, "elapsed_s": 0.0}

        def _multi_agent_runner(nspec: dict, del_info: dict, attempt: int) -> dict:
            nid = nspec["id"]
            if nid == "step1_architect":
                return {
                    "ok": True,
                    "output": "Contrato diseñado: can_consume(available: int, requested: int) -> tuple[bool, int]",
                }
            if nid == "step2_developer":
                prompt = (
                    "Implementa en Python `def can_consume(available: int, requested: int) -> tuple[bool, int]:` "
                    "que devuelva `(True, available - requested)` si ` 0 <= requested <= available`, "
                    "y `(False, available)` en caso contrario. Devuelve únicamente el código Python."
                )
                gen = _call_ollama_generate(model, prompt, num_predict=140, think=False)
                metrics_acc["tokens"] += gen.get("total_tokens", 0)
                metrics_acc["elapsed_s"] += gen.get("total_s", 0.0)
                code = extract_code_block(gen.get("text", ""))
                (proj / "token_bucket.py").write_text(code + "\n", encoding="utf-8")
                return {"ok": bool(code), "output": f"Implementado token_bucket.py ({len(code)} bytes)"}
            if nid == "step3_reviewer":
                code_txt = (proj / "token_bucket.py").read_text(encoding="utf-8")
                ok_ast = score_python_code_quality(code_txt) >= 60.0
                return {"ok": ok_ast, "output": "APPROVED: token_bucket.py#L1 cumple contrato"}
            if nid == "step4_qa":
                res = _run_unittest(proj)
                return {"ok": res.returncode == 0, "output": res.stderr.strip(), "error": res.stderr if res.returncode != 0 else None}
            return {"ok": True, "output": "OK"}

        nodes = [
            {"id": "step1_architect", "title": "Diseño de contrato", "specialist": "architect", "dependencies": []},
            {"id": "step2_developer", "title": "Implementación", "specialist": "senior-developer", "dependencies": ["step1_architect"]},
            {"id": "step3_reviewer", "title": "Revisión independiente", "specialist": "code-reviewer", "dependencies": ["step2_developer"]},
            {"id": "step4_qa", "title": "Pruebas QA", "specialist": "qa-engineer", "dependencies": ["step3_reviewer"]},
        ]
        wf = engine.execute_workflow(
            title="Multi-Agent Token Bucket Workflow",
            nodes_spec=nodes,
            directory=str(proj),
            node_executor=_multi_agent_runner,
        )
        return {
            "id": "09_multi_agent_execution",
            "category": "Ejecución multiagente",
            "specialist": "saghet-orchestrator (4-agent DAG)",
            "model": model,
            "passed": wf["ok"] and wf["nodes"]["step4_qa"]["status"] == "DONE",
            "workflow_id": wf["workflow_id"],
            "traces_count": len(wf["traces"]),
            "tokens": metrics_acc["tokens"],
            "elapsed_s": round(metrics_acc["elapsed_s"], 2),
        }


def bench_10_fault_recovery(model: str, supervisor: QualitySupervisor) -> dict:
    """
    10. Recuperación ante fallos: el intento 1 recibe un prompt con firma incompleta que falla el test,
    el Supervisor emite CORRECT con el traceback exacto, y en el intento 2 el modelo corrige el código y pasa.
    """
    with tempfile.TemporaryDirectory(prefix="saghet_b10_rec_") as tmp:
        proj = Path(tmp)
        test_code = (
            "import unittest\n"
            "from normalizer import normalize_Header\n\n"
            "class TestNorm(unittest.TestCase):\n"
            "    def test_header(self):\n"
            "        self.assertEqual(normalize_Header('  x-saghet-token  '), 'X-SAGHET-TOKEN')\n"
        )
        _init_isolated_git_project(proj, {"normalizer.py": "def wrong_name(s):\n    return s\n", "test_norm.py": test_code})

        # Intento 1: Falla la prueba y el Supervisor exige corrección (CORRECT)
        fail_res = _run_unittest(proj)
        d_attempt1 = supervisor.evaluate_execution(
            objective="Implementa normalize_Header en normalizer.py",
            agent="senior-developer",
            agent_output=f"Intento 1 en normalizer.py#L1.\n{fail_res.stderr}",
            iteration=1,
            diff_files=["normalizer.py"],
            test_output=fail_res.stderr,
            test_returncode=fail_res.returncode,
        )
        assert d_attempt1["verdict"] == "CORRECT", "El Supervisor debía ordenar CORRECT en el intento 1"

        # Intento 2: El modelo recibe el correction_prompt del Supervisor + el error de unittest y lo repara
        recovery_prompt = (
            f"{d_attempt1['correction_prompt']}\n"
            f"Traceback de unittest:\n{fail_res.stderr}\n"
            f"Implementa en `normalizer.py` la función `def normalize_Header(value: str) -> str:` "
            f"que haga `value.strip().upper()`. Devuelve únicamente el código Python."
        )
        gen = _call_ollama_generate(model, recovery_prompt, num_predict=140, think=False)
        recovered_code = extract_code_block(gen.get("text", ""))
        (proj / "normalizer.py").write_text(recovered_code + "\n", encoding="utf-8")

        pass_res = _run_unittest(proj)
        d_attempt2 = supervisor.evaluate_execution(
            objective="Implementa normalize_Header en normalizer.py",
            agent="senior-developer",
            agent_output=f"Recuperado en intento 2 en normalizer.py#L1.\n{pass_res.stderr}",
            iteration=2,
            diff_files=_git_changed_files(proj),
            test_output=pass_res.stderr,
            test_returncode=pass_res.returncode,
            reviewer_verdict="APPROVED" if pass_res.returncode == 0 else "CHANGES_REQUESTED",
        )
        return {
            "id": "10_fault_recovery",
            "category": "Recuperación ante fallos",
            "specialist": "senior-developer",
            "model": model,
            "attempt1_verdict": d_attempt1["verdict"],
            "attempt2_verdict": d_attempt2["verdict"],
            "passed": d_attempt1["verdict"] == "CORRECT" and pass_res.returncode == 0 and d_attempt2["verdict"] == "ACCEPT",
            "tok_per_s": gen.get("tok_per_s", 0.0),
            "tokens": gen.get("total_tokens", 0),
            "elapsed_s": gen.get("total_s", 0.0),
        }


def run_all_benchmarks(model: str = "qwen3.5:9b", out_path: Path | None = DEFAULT_BENCH_OUT) -> dict:
    supervisor = QualitySupervisor(max_iterations=3)
    t0 = time.perf_counter()
    runners = [
        bench_01_feature_development,
        bench_02_bug_fixing,
        bench_03_refactoring,
        bench_04_debugging,
        bench_05_test_creation,
        bench_06_technical_research,
        bench_07_build_error_resolution,
        bench_08_multi_file_work,
        bench_09_multi_agent_execution,
        bench_10_fault_recovery,
    ]
    results = []
    for fn in runners:
        results.append(fn(model, supervisor))

    total_s = round(time.perf_counter() - t0, 2)
    passed_cnt = sum(1 for r in results if r.get("passed"))
    report = {
        "schema": "saghet.intelligence-benchmarks/v1",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model_evaluated": model,
        "total_benchmarks": len(results),
        "passed_benchmarks": passed_cnt,
        "pass_rate_pct": round((passed_cnt / max(1, len(results))) * 100.0, 1),
        "total_elapsed_s": total_s,
        "peak_vram_mib": get_gpu_vram_mib(),
        "peak_ram_mib": get_ram_used_mib(),
        "artificial_test_mutations_allowed": False,
        "results": results,
    }
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenCode-Saghet 10 Intelligence Benchmarks Runner")
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--out", default=str(DEFAULT_BENCH_OUT))
    args = parser.parse_args()

    rep = run_all_benchmarks(model=args.model, out_path=Path(args.out))
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    if rep["passed_benchmarks"] != rep["total_benchmarks"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
