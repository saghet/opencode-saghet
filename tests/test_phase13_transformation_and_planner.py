#!/usr/bin/env python3
"""
Pruebas reales End-to-End para Fases 4, 5 y 7 (Etapa 5):
- Transformación CLI -> Web ejecutable (servidor HTTP real + API + frontend + CLI preservada + Matriz de Equivalencia).
- Transformación CLI -> Desktop PyQt6 ejecutable (ventana real QT_QPA_PLATFORM=offscreen + clicks reales + Matriz de Equivalencia).
- Validador Anti-UI Falsa (rechaza botones decorativos, datos simulados y wrappers CLI).
- Intelligent Task Planner (7 categorías, alternativas, aclaración ante ambigüedad, 0 conflictos de archivos).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.intelligence.task_planner import IntelligentTaskPlanner, classify_engineering_task
from scripts.intelligence.transformation_engine import SemanticTransformationEngine, analyze_cli_application
from scripts.intelligence.visual_product import select_product_stack, validate_ui_product_integrity

SAMPLE_CLI_SOURCE = '''#!/usr/bin/env python3
"""Herramienta CLI real de cálculo de presupuestos y análisis de texto."""
import argparse
import json


def calc_budget(subtotal: float, tax_rate: float = 0.19, currency: str = "USD") -> dict:
    """Calcula impuestos y total neto con redondeo bancario a 2 decimales."""
    tax = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax, 2)
    return {"subtotal": round(subtotal, 2), "tax": tax, "total": total, "currency": currency}


def word_stats(text: str) -> dict:
    """Cuenta palabras, caracteres sin espacios y palabra más larga."""
    words = [w for w in text.split() if w]
    longest = max(words, key=len) if words else ""
    return {"words": len(words), "chars_no_space": len(text.replace(" ", "")), "longest": longest}


def main():
    parser = argparse.ArgumentParser(description="Budget & Text CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_budget = sub.add_parser("budget", help="Calcula presupuesto con impuestos")
    p_budget.add_argument("subtotal", type=float)
    p_budget.add_argument("--tax-rate", type=float, default=0.19)
    p_budget.add_argument("--currency", choices=["USD", "EUR", "COP"], default="USD")
    p_budget.set_defaults(func=calc_budget)

    p_stats = sub.add_parser("stats", help="Analiza métricas de un texto")
    p_stats.add_argument("text", type=str)
    p_stats.set_defaults(func=word_stats)

    args = parser.parse_args()
    if args.command == "budget":
        print(json.dumps(calc_budget(args.subtotal, args.tax_rate, args.currency), sort_keys=True))
    elif args.command == "stats":
        print(json.dumps(word_stats(args.text), sort_keys=True))


if __name__ == "__main__":
    main()
'''


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_port(port: int, timeout: float = 6.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.08)
    return False


class TestPhase13TransformationAndPlanner(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.cli_dir = self.root / "orig_cli"
        self.cli_dir.mkdir()
        self.cli_file = self.cli_dir / "tool.py"
        self.cli_file.write_text(SAMPLE_CLI_SOURCE, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_01_cli_to_web_real_server_and_functional_equivalence(self) -> None:
        analysis = analyze_cli_application(self.cli_dir)
        self.assertTrue(analysis["ok"])
        self.assertEqual(analysis["commands_count"], 2)

        web_out = self.root / "web_app"
        engine = SemanticTransformationEngine()
        res = engine.transform_cli_to_web(self.cli_dir, web_out, app_title="Budget & Text Web Studio")
        self.assertTrue(res["ok"], f"UI integrity issues: {res.get('ui_integrity_validation')}")
        self.assertTrue(res["ui_integrity_validation"]["ok"])

        # Arrancar servidor web real generado y probar endpoints + equivalencia funcional
        port = _free_port()
        proc = subprocess.Popen(
            [sys.executable, str(web_out / "api" / "server.py"), "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self.assertTrue(_wait_port(port), "El servidor web transformado no levantó")
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=4) as r:
                html = r.read().decode("utf-8")
            self.assertIn("Budget & Text Web Studio", html)
            self.assertIn("<main", html)

            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/capabilities", timeout=4) as r:
                caps = json.loads(r.read().decode("utf-8"))
            self.assertEqual(len(caps["capabilities"]), 2)

            cases = [
                {
                    "feature": "Calculo de presupuesto",
                    "command": "budget",
                    "cli_args": ["budget", "250.0", "--tax-rate", "0.10", "--currency", "EUR"],
                    "payload": {"subtotal": 250.0, "tax_rate": 0.10, "currency": "EUR"},
                },
                {
                    "feature": "Estadisticas de texto",
                    "command": "stats",
                    "cli_args": ["stats", "ingenieria inteligente saghet"],
                    "payload": {"text": "ingenieria inteligente saghet"},
                },
            ]

            def run_orig(case: dict) -> str:
                r = subprocess.run([sys.executable, str(self.cli_file), *case["cli_args"]], capture_output=True, text=True, check=True)
                return json.dumps(json.loads(r.stdout), sort_keys=True)

            def run_web_api(case: dict) -> str:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/actions/{case['command']}",
                    data=json.dumps(case["payload"]).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=4) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(body["ok"])
                return json.dumps(body["result"], sort_keys=True)

            equiv = engine.verify_functional_equivalence(cases, run_orig, run_web_api)
            self.assertTrue(equiv["ok"], f"Equivalencia fallida: {equiv}")
            self.assertEqual(equiv["equivalence_rate_pct"], 100.0)

            # Verificar que el adaptador CLI preservado también sigue funcionando idéntico
            preserved = subprocess.run(
                [sys.executable, str(web_out / "adapters" / "cli.py"), "budget", "250.0", "--tax-rate", "0.10", "--currency", "EUR"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(json.dumps(json.loads(preserved.stdout), sort_keys=True), run_orig(cases[0]))
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_02_cli_to_desktop_pyqt6_offscreen_real_execution(self) -> None:
        desk_out = self.root / "desktop_app"
        engine = SemanticTransformationEngine()
        res = engine.transform_cli_to_desktop(self.cli_dir, desk_out, app_title="Budget & Text Desktop")
        self.assertTrue(res["ok"], f"Desktop UI integrity failed: {res.get('ui_integrity_validation')}")
        self.assertTrue(res["pyqt6_available"], "PyQt6 debe estar disponible en este entorno Garuda Linux")

        # Ejecutar instancia real de la ventana PyQt6 en modo offscreen y disparar clicks reales
        probe_script = f"""
import json, sys
sys.path.insert(0, {str(desk_out)!r})
from PyQt6.QtWidgets import QApplication
from desktop.app import DesktopProductWindow

app = QApplication([])
win = DesktopProductWindow()
win.nav_list.setCurrentRow(0)
win.field_widgets["subtotal"].setText("100.0")
win.field_widgets["tax_rate"].setText("0.15")
idx = win.field_widgets["currency"].findText("USD")
win.field_widgets["currency"].setCurrentIndex(idx)
win.run_button.click()
out0 = json.dumps(json.loads(win.output_view.toPlainText()), sort_keys=True)

win.nav_list.setCurrentRow(1)
win.field_widgets["text"].setText("hola mundo desktop")
win.run_button.click()
out1 = json.dumps(json.loads(win.output_view.toPlainText()), sort_keys=True)
print(json.dumps({{"budget": out0, "stats": out1}}))
"""
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        proc = subprocess.run([sys.executable, "-c", probe_script], capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(proc.returncode, 0, f"PyQt6 offscreen fallo: {proc.stderr}")
        gui_outputs = json.loads(proc.stdout.strip().splitlines()[-1])

        orig_budget = json.dumps(
            json.loads(subprocess.run([sys.executable, str(self.cli_file), "budget", "100.0", "--tax-rate", "0.15", "--currency", "USD"], capture_output=True, text=True, check=True).stdout),
            sort_keys=True,
        )
        orig_stats = json.dumps(
            json.loads(subprocess.run([sys.executable, str(self.cli_file), "stats", "hola mundo desktop"], capture_output=True, text=True, check=True).stdout),
            sort_keys=True,
        )
        self.assertEqual(gui_outputs["budget"], orig_budget)
        self.assertEqual(gui_outputs["stats"], orig_stats)

    def test_03_anti_fake_ui_validator_rejects_bad_ui(self) -> None:
        fake_dir = self.root / "fake_ui"
        fake_dir.mkdir()
        (fake_dir / "index.html").write_text(
            "<div><button>Botón Decorativo</button><pre>$ mycli --run</pre><p>Copia y ejecuta en tu terminal</p></div>",
            encoding="utf-8",
        )
        (fake_dir / "app.js").write_text("const mockData = [{id: 1}]; // TODO: connect API\n", encoding="utf-8")
        check = validate_ui_product_integrity(fake_dir)
        self.assertFalse(check["ok"])
        codes = {v["code"] for v in check["violations"]}
        self.assertIn("decorative_unwired_button", codes)
        self.assertIn("cli_command_printer_antipattern", codes)
        self.assertIn("fake_or_placeholder_ui", codes)
        self.assertIn("unwired_frontend_no_api_call", codes)

    def test_04_intelligent_task_planner_and_stack_selection(self) -> None:
        self.assertEqual(classify_engineering_task("Convierte esta herramienta CLI en una aplicación web moderna"), "interface_transformation")
        self.assertEqual(classify_engineering_task("Corrige el bug de timeout en server.py"), "repair")
        self.assertEqual(classify_engineering_task("Refactoriza el módulo de autenticación desacoplando dominio"), "refactoring")
        self.assertEqual(classify_engineering_task("Migra la base de datos de SQLite a PostgreSQL"), "migration")
        self.assertEqual(classify_engineering_task("Integra la API de GitHub y Context7"), "integration")
        self.assertEqual(classify_engineering_task("Analiza la arquitectura del repositorio"), "research")
        self.assertEqual(classify_engineering_task("Construye un servicio de facturación"), "new_development")

        stack = select_product_stack("web", "Python", "medium")
        self.assertTrue(stack["single_coherent_stack"])
        self.assertEqual(stack["stack_id"], "react_fastapi")

        planner = IntelligentTaskPlanner()
        plan = planner.build_plan("Convierte esta herramienta CLI en una aplicación web moderna", project_path=self.cli_dir)
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["task_category"], "interface_transformation")
        self.assertEqual(len(plan["file_ownership_conflicts"]), 0)
        self.assertFalse(plan["requires_clarification"])
        self.assertTrue(any("Matriz de Equivalencia" in t for t in plan["acceptance_tests"]))

        # Si no especifica plataforma destino en transformación, debe pedir aclaración
        amb_plan = planner.build_plan("Transforma esta herramienta CLI en otra interfaz")
        self.assertTrue(amb_plan["requires_clarification"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
