#!/usr/bin/env python3
"""Pruebas unitarias y de integración para Fase 3: Project Intelligence & Continuity."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.memory.hierarchical_memory import HierarchicalMemoryStore
from scripts.memory.project_intelligence import ProjectIntelligenceEngine


class TestPhase3ProjectIntelligence(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory(prefix="saghet_p3_proj_")
        self.root = Path(self.tmp_dir.name)
        self.proj_dir = self.root / "sample_repo"
        self.proj_dir.mkdir(parents=True)
        self.mem_store = HierarchicalMemoryStore(db_path=self.root / "mem.db")
        self.engine = ProjectIntelligenceEngine(db_path=self.root / "proj.db", memory_store=self.mem_store)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_01_incremental_indexing_and_ignores(self) -> None:
        (self.proj_dir / "auth.py").write_text(
            "def verify_token(token: str) -> bool:\n"
            "    \"\"\"Verifica firma del token.\"\"\"\n"
            "    return token.startswith('ok_')\n",
            encoding="utf-8",
        )
        (self.proj_dir / "api.py").write_text(
            "from auth import verify_token\n\n"
            "def handle_request(tok: str) -> int:\n"
            "    return 200 if verify_token(tok) else 401\n",
            encoding="utf-8",
        )
        (self.proj_dir / "test_api.py").write_text(
            "from api import handle_request\n\ndef test_ok():\n    assert handle_request('ok_1') == 200\n",
            encoding="utf-8",
        )
        # Directorio ignorado
        nm = self.proj_dir / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("function ignored() {}\n", encoding="utf-8")

        res1 = self.engine.index_project(self.proj_dir)
        self.assertTrue(res1["ok"])
        self.assertEqual(res1["total_files"], 3)
        self.assertEqual(res1["reindexed"], 3)

        # Segunda ejecución sin cambios -> 0 reindexados
        res2 = self.engine.index_project(self.proj_dir)
        self.assertEqual(res2["reindexed"], 0)
        self.assertEqual(res2["unchanged"], 3)

    def test_02_symbol_impact_tests_and_memory_constraints(self) -> None:
        (self.proj_dir / "billing.py").write_text(
            "def compute_total(amount: float) -> float:\n    return round(amount * 1.1, 2)\n",
            encoding="utf-8",
        )
        (self.proj_dir / "checkout.py").write_text(
            "from billing import compute_total\n\n"
            "def finalize_order(x: float) -> float:\n    return compute_total(x)\n",
            encoding="utf-8",
        )
        (self.proj_dir / "test_billing.py").write_text(
            "from billing import compute_total\n", encoding="utf-8"
        )
        self.engine.index_project(self.proj_dir)

        self.mem_store.store_memory(
            tier="project",
            category="architectural_decision",
            title="Regla de redondeo en billing",
            content="Mantener redondeo a 2 decimales en billing.py.",
            provenance="architect:billing",
            project_path=str(self.proj_dir),
        )

        syms = self.engine.find_symbol("compute_total", self.proj_dir)
        self.assertEqual(len(syms), 1)
        self.assertEqual(syms[0]["rel_path"], "billing.py")

        impact = self.engine.get_impact_and_tests("billing.py", self.proj_dir)
        self.assertIn("checkout.py", impact["dependent_files"])
        self.assertIn("test_billing.py", impact["related_tests"])
        self.assertGreaterEqual(len(impact["constraining_decisions"]), 1)

    def test_03_project_continuity_across_sessions(self) -> None:
        subprocess.run(["git", "init", "-b", "main", str(self.proj_dir)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.proj_dir), "config", "user.email", "t@saghet.local"], check=True)
        subprocess.run(["git", "-C", str(self.proj_dir), "config", "user.name", "Test"], check=True)
        (self.proj_dir / "app.py").write_text("def run():\n    return True\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.proj_dir), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.proj_dir), "commit", "-m", "init"], check=True, capture_output=True)

        save_res = self.engine.save_project_state(
            project_path=self.proj_dir,
            goals=["Construir API resiliente"],
            architecture_summary="Modular Python + SQLite",
            completed_features=["Endpoint /health verificado"],
            pending_features=["Rate limiting"],
            known_issues=[],
            decisions=["Usar SQLite local"],
            test_summary={"passed": 5, "failed": 0},
            next_recommended_step="Implementar rate limiter en middleware",
        )
        self.assertTrue(save_res["ok"])

        ctx = self.engine.reconstruct_continuity_context(self.proj_dir)
        self.assertTrue(ctx["has_saved_state"])
        self.assertEqual(ctx["completed_features"], ["Endpoint /health verificado"])
        self.assertEqual(ctx["pending_features"], ["Rate limiting"])
        self.assertEqual(ctx["next_recommended_step"], "Implementar rate limiter en middleware")
        self.assertEqual(ctx["live_git"]["branch"], "main")

    def test_04_real_opencode_saghet_repo_indexing(self) -> None:
        res = self.engine.index_project(REPO_DIR)
        self.assertTrue(res["ok"])
        self.assertGreater(res["total_files"], 20)
        hits = self.engine.find_symbol("QualitySupervisor", REPO_DIR)
        self.assertTrue(any(h["rel_path"].endswith("quality_supervisor.py") for h in hits))


if __name__ == "__main__":
    unittest.main()
