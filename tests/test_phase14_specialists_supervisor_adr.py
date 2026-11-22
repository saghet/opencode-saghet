#!/usr/bin/env python3
"""Pruebas unitarias para Fases 6, 8 y 9 (Etapa 6): 9 Especialistas, Quality Gate y Memoria ADR."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.memory.hierarchical_memory import HierarchicalMemoryStore
from scripts.supervisor.gentle_ai_bridge import classify_and_route
from scripts.supervisor.quality_supervisor import QualitySupervisor
from scripts.supervisor.session_diagnostics import KNOWN_AGENT_NAMES

NEW_SPECIALISTS = (
    "semantic-architecture-specialist",
    "repository-intelligence-specialist",
    "code-reuse-specialist",
    "software-transformation-specialist",
    "domain-engineering-specialist",
    "frontend-product-engineer",
    "api-integration-specialist",
    "architecture-validation-specialist",
    "license-compliance-specialist",
)
NEW_READONLY = (
    "semantic-architecture-specialist",
    "repository-intelligence-specialist",
    "architecture-validation-specialist",
    "license-compliance-specialist",
)


class TestPhase14SpecialistsSupervisorADR(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_01_opencode_template_has_google_gemini4_and_9_new_specialists(self) -> None:
        cfg = json.loads((REPO_DIR / "config" / "opencode.json.tpl").read_text(encoding="utf-8"))
        # Proveedor oficial Google Gemini + Ollama preservado
        self.assertIn("google", cfg["provider"])
        self.assertIn("ollama", cfg["provider"])
        self.assertEqual(cfg["provider"]["google"]["npm"], "@ai-sdk/google")
        self.assertIn("gemini-4-neon", cfg["provider"]["google"]["models"])
        self.assertEqual(cfg["provider"]["google"]["models"]["gemini-4-neon"]["limit"]["context"], 1048576)

        agents = cfg["agent"]
        task_perm = cfg["permission"]["task"]
        self.assertEqual(task_perm.get("*"), "deny")
        for name in NEW_SPECIALISTS:
            self.assertIn(name, agents, f"Falta especialista {name}")
            self.assertEqual(task_perm.get(name), "allow", f"Falta {name} en permission.task")
            self.assertIn(name, KNOWN_AGENT_NAMES, f"Falta {name} en KNOWN_AGENT_NAMES")
            self.assertFalse((agents[name].get("tools") or {}).get("subagent", True), f"{name} debe tener subagent=false")

        for ro in NEW_READONLY:
            tools = agents[ro]["tools"]
            self.assertFalse(tools.get("write", True))
            self.assertFalse(tools.get("edit", True))
            self.assertFalse(tools.get("bash", True))

    def test_02_gentle_ai_routes_to_new_specialists(self) -> None:
        r_tr = classify_and_route("Convierte esta herramienta CLI a web con equivalencia funcional")
        self.assertEqual(r_tr["primary_specialist"], "software-transformation-specialist")

        r_reuse = classify_and_route("Investiga reutilización de código en GitHub para parsers")
        self.assertIn("code_reuse", r_reuse["domains"])

        r_lic = classify_and_route("Audita la licencia SPDX y atribución de esta librería GPL")
        self.assertIn("license_compliance", r_lic["domains"])

    def test_03_transformation_quality_gate_enforces_equivalence_and_anti_fake_ui(self) -> None:
        sup = QualitySupervisor()
        good_dir = self.root / "good_ui"
        good_dir.mkdir()
        (good_dir / "index.html").write_text(
            "<main><form><button type='submit'>Run</button></form></main>",
            encoding="utf-8",
        )
        (good_dir / "app.js").write_text("fetch('/api/actions/run');", encoding="utf-8")

        # Sin aprobación independiente -> CORRECT
        d1 = sup.evaluate_transformation_delivery(
            objective="CLI a Web",
            output_dir=good_dir,
            equivalence_report={"ok": True, "passed": 2, "total": 2, "equivalence_rate_pct": 100.0},
            reviewer_verdict=None,
        )
        self.assertEqual(d1["verdict"], "CORRECT")

        # Con pruebas no ejecutables declaradas -> PARTIAL_UNVERIFIED (jamás ACCEPT falso)
        d2 = sup.evaluate_transformation_delivery(
            objective="CLI a Web",
            output_dir=good_dir,
            equivalence_report={"ok": True, "passed": 2, "total": 2, "equivalence_rate_pct": 100.0},
            reviewer_verdict="APPROVED",
            unrunnable_tests=["e2e_mobile_ios_simulator"],
        )
        self.assertEqual(d2["verdict"], "PARTIAL_UNVERIFIED")
        self.assertIn("e2e_mobile_ios_simulator", d2["unrunnable_tests_declared"])

        # Todo verificado + APPROVED -> ACCEPT
        d3 = sup.evaluate_transformation_delivery(
            objective="CLI a Web",
            output_dir=good_dir,
            equivalence_report={"ok": True, "passed": 2, "total": 2, "equivalence_rate_pct": 100.0},
            reviewer_verdict="APPROVED",
        )
        self.assertEqual(d3["verdict"], "ACCEPT")

    def test_04_technical_decision_memory_structured_and_verified_only(self) -> None:
        mem = HierarchicalMemoryStore(db_path=self.root / "adr_mem.db")
        r_ver = mem.record_technical_decision(
            problem="Acoplamiento entre CLI argparse y reglas de cálculo",
            alternatives_evaluated=["Wrapper xterm.js", "Extracción Domain/Application/API"],
            decision="Separar Domain y Application preservando adaptador CLI",
            justification="Permite equivalencia 1:1 y reutilización en Web y Desktop",
            consequences=["Mayor modularidad", "Requiere pruebas de equivalencia"],
            project_path=str(self.root),
            verified=True,
        )
        self.assertTrue(r_ver["ok"])
        self.assertEqual(r_ver["status"], "valid")

        # Hipótesis no verificada queda provisional y no contamina decisiones verificadas
        r_hyp = mem.record_technical_decision(
            problem="Hipótesis sin probar",
            alternatives_evaluated=["A", "B"],
            decision="Probar caché distribuida sin benchmarks",
            justification="Sospecha inicial",
            consequences=["Riesgo de complejidad"],
            project_path=str(self.root),
            verified=False,
        )
        self.assertTrue(r_hyp["ok"])
        self.assertEqual(r_hyp["status"], "provisional")

        verified_list = mem.list_technical_decisions(project_path=str(self.root), include_unverified=False)
        self.assertEqual(len(verified_list), 1)
        self.assertEqual(verified_list[0]["decision"], "Separar Domain y Application preservando adaptador CLI")
        self.assertEqual(len(verified_list[0]["alternatives_evaluated"]), 2)

    def test_05_dashboard_intelligence_endpoints_preserve_p0_security(self) -> None:
        import socket
        import subprocess
        import time
        import urllib.error
        import urllib.request

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = int(s.getsockname()[1])

        tok_file = Path.home() / ".config" / "opencode" / ".saghet-dashboard-token"
        token = tok_file.read_text(encoding="utf-8").strip() if tok_file.is_file() else ""
        proc = subprocess.Popen(
            [sys.executable, str(REPO_DIR / "dashboard" / "server.py"), "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            ready = False
            for _ in range(50):
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        ready = True
                        break
                except OSError:
                    time.sleep(0.1)
            self.assertTrue(ready, "Dashboard server no levantó")

            # GET /api/intelligence/status debe responder 200
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/intelligence/status", timeout=4) as r:
                st = json.loads(r.read().decode("utf-8"))
            self.assertTrue(st["ok"])
            self.assertEqual(st["gemini_core"]["model_id"], "gemini-4-neon")

            # POST sin token debe ser rechazado con 401/403 (P0 Security)
            req_unauth = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/intelligence/plan",
                data=json.dumps({"objective": "Convierte CLI a web"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req_unauth, timeout=4)
            self.assertIn(ctx.exception.code, (401, 403))
            ctx.exception.close()

            # POST con token válido debe devolver plan estructurado
            if token:
                req_auth = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/intelligence/plan",
                    data=json.dumps({"objective": "Convierte esta CLI en aplicación web", "directory": str(REPO_DIR)}).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Origin": f"http://127.0.0.1:{port}",
                        "X-Saghet-Token": token,
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req_auth, timeout=6) as r:
                    plan = json.loads(r.read().decode("utf-8"))
                self.assertTrue(plan["ok"])
                self.assertEqual(plan["task_category"], "interface_transformation")
        finally:
            proc.terminate()
            proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
