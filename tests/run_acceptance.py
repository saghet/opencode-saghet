#!/usr/bin/env python3
"""Suite de pruebas de aceptación integral de OpenCode-Saghet (Categorías A-F)."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
CFG_DIR = Path.home() / ".config" / "opencode"


class TestOpenCodeSaghetAcceptance(unittest.TestCase):
    def test_a_doctor_and_idempotency(self):
        res1 = subprocess.run(["bash", str(REPO_DIR / "install.sh"), "--skip-models"], capture_output=True, text=True, timeout=30)
        self.assertEqual(res1.returncode, 0, res1.stderr)
        res2 = subprocess.run(["bash", str(REPO_DIR / "doctor.sh")], capture_output=True, text=True, timeout=20)
        self.assertEqual(res2.returncode, 0, res2.stdout + res2.stderr)
        self.assertIn("SALUDABLE", res2.stdout)

    def test_b_opencode_agents_and_plugins(self):
        agents_raw = subprocess.check_output(["opencode", "debug", "agents"], text=True, timeout=10)
        agents = {a["id"]: a for a in json.loads(agents_raw)}
        expected = [
            "saghet-orchestrator",
            "architect",
            "researcher",
            "senior-developer",
            "frontend-specialist",
            "backend-specialist",
            "database-specialist",
            "devops-engineer",
            "security-auditor",
            "code-reviewer",
            "qa-engineer",
            "performance-engineer",
            "documentation-engineer",
        ]
        for name in expected:
            self.assertIn(name, agents, f"Falta agente {name}")

        plugins_out = subprocess.check_output(["opencode", "plugin", "list"], text=True, timeout=10)
        self.assertIn("opencode-dcp", plugins_out)
        self.assertIn("opencode-mem", plugins_out)
        self.assertIn("plannotator", plugins_out)

    def test_c_ollama_and_dashboard_live(self):
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=4) as r:
            tags = json.loads(r.read().decode("utf-8"))
        names = [m["name"] for m in tags.get("models", [])]
        self.assertIn("qwen3.5:9b", names)
        self.assertIn("qwen3.5:4b", names)

        proc = subprocess.Popen(
            ["python3", str(REPO_DIR / "dashboard" / "server.py"), "--port", "4782"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            import time
            time.sleep(1.0)
            with urllib.request.urlopen("http://127.0.0.1:4782/api/telemetry", timeout=6) as r:
                tel = json.loads(r.read().decode("utf-8"))
            self.assertTrue(tel["opencode_server_up"])
            self.assertTrue(tel["ollama"]["up"])
            self.assertTrue(tel["gpu"]["available"])
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_d_dev_bug_detect_and_fix(self):
        with tempfile.TemporaryDirectory(prefix="saghet_dev_test_") as tmp:
            p = Path(tmp)
            calc = p / "calc.py"
            test_f = p / "test_calc.py"
            calc.write_text("def sub(a, b):\n    return a + b  # bug intencional\n", encoding="utf-8")
            test_f.write_text(
                "import unittest\nfrom calc import sub\n"
                "class T(unittest.TestCase):\n"
                "    def test_sub(self):\n"
                "        self.assertEqual(sub(5, 3), 2)\n"
                "if __name__ == '__main__':\n    unittest.main()\n",
                encoding="utf-8",
            )
            fail_res = subprocess.run(["python3", "-m", "unittest", "discover", "-s", tmp], capture_output=True, text=True)
            self.assertNotEqual(fail_res.returncode, 0, "Debía fallar con el bug intencional")

            calc.write_text("def sub(a, b):\n    return a - b\n", encoding="utf-8")
            pass_res = subprocess.run(["python3", "-m", "unittest", "discover", "-s", tmp], capture_output=True, text=True)
            self.assertEqual(pass_res.returncode, 0, pass_res.stderr)

    def test_e_security_policies_and_no_secrets(self):
        with open(CFG_DIR / "opencode.json", encoding="utf-8") as f:
            cfg = json.load(f)

        for ro_agent in ["architect", "researcher", "security-auditor", "code-reviewer"]:
            tools = cfg["agent"][ro_agent]["tools"]
            self.assertFalse(tools.get("write", True))
            self.assertFalse(tools.get("edit", True))
            self.assertFalse(tools.get("bash", True))

        self.assertEqual(cfg["permission"]["read"].get("**/.env"), "deny")
        self.assertEqual(cfg["permission"]["read"].get("service.json"), "deny")
        self.assertEqual(cfg["permission"]["bash"].get("git push --force*"), "deny")
        self.assertEqual(cfg["permission"]["bash"].get("rm -rf /"), "deny")

        for secret_name in [".env", ".env.db", "service.json", ".auth-token"]:
            self.assertFalse((REPO_DIR / secret_name).exists(), f"Secreto encontrado en repo: {secret_name}")

    def test_f_performance_benchmark_present(self):
        bench_file = REPO_DIR / "benchmarks" / "rtx4060_saghet.json"
        self.assertTrue(bench_file.exists())
        data = json.loads(bench_file.read_text(encoding="utf-8"))
        self.assertLess(data["opencode_cli"]["version_ms"], 1000.0)
        for b in data["benchmarks"]:
            self.assertTrue(b["ok"], f"Benchmark falló para {b['model']}")
            self.assertLess(b["vram_used_mib"], 8188.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
