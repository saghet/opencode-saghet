#!/usr/bin/env python3
"""Pruebas unitarias para Fase 2 / Etapa 3: Semantic Project Understanding Engine."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.intelligence.semantic_engine import SemanticProjectEngine
from scripts.memory.hierarchical_memory import HierarchicalMemoryStore


class TestPhase11SemanticEngine(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.proj = self.root / "sample_app"
        self.proj.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _build_sample_repo(self) -> None:
        (self.proj / "requirements.txt").write_text("fastapi==0.115.0\npytest==8.3.0\n", encoding="utf-8")
        (self.proj / "core").mkdir()
        (self.proj / "core" / "pricing.py").write_text(
            "def calculate_discount(price: float, rate: float) -> float:\n"
            "    return round(price * (1.0 - rate), 2)\n\n"
            "class InvoiceService:\n"
            "    def total(self, price: float, rate: float) -> float:\n"
            "        return calculate_discount(price, rate)\n"
            "    def currency(self) -> str:\n"
            "        return 'USD'\n"
            "    def validate(self, price: float) -> bool:\n"
            "        return price >= 0\n",
            encoding="utf-8",
        )
        (self.proj / "api").mkdir()
        (self.proj / "api" / "routes.py").write_text(
            "from fastapi import FastAPI\n"
            "from core.pricing import calculate_discount, InvoiceService\n"
            "app = FastAPI()\n"
            "@app.get('/api/price')\n"
            "def get_price(amount: float) -> dict:\n"
            "    svc = InvoiceService()\n"
            "    return {'total': svc.total(amount, 0.1), 'discounted': calculate_discount(amount, 0.1)}\n",
            encoding="utf-8",
        )
        (self.proj / "tests").mkdir()
        (self.proj / "tests" / "test_pricing.py").write_text(
            "from core.pricing import calculate_discount\n"
            "def test_discount():\n"
            "    assert calculate_discount(100.0, 0.1) == 90.0\n",
            encoding="utf-8",
        )

    def test_01_codebase_intelligence_and_repository_graph(self) -> None:
        self._build_sample_repo()
        mem = HierarchicalMemoryStore(db_path=self.root / "mem.db")
        eng = SemanticProjectEngine(db_path=self.root / "pi.db", memory_store=mem)
        analysis = eng.analyze_codebase(self.proj)

        self.assertTrue(analysis["ok"])
        ci = analysis["codebase_intelligence"]
        self.assertEqual(ci["primary_language"], "Python")
        self.assertIn("FastAPI", ci["frameworks"])
        self.assertIn("core/pricing.py", ci["business_logic_files"])
        self.assertTrue(any(c["symbol"] == "calculate_discount" and c["decoupled_from_ui"] for c in ci["reusable_components"]))

        rg = analysis["repository_graph"]
        self.assertGreaterEqual(rg["functions_count"], 3)
        self.assertTrue(any(s["name"] == "InvoiceService" for s in rg["services"]))
        self.assertTrue(any(c["path"] == "/api/price" and c["method"] == "GET" for c in rg["interface_contracts"]))
        self.assertTrue(any(e["from"] == "api" and e["to"] == "core" for e in rg["module_relations"]))

        # Incremental cache hit on second pass
        analysis2 = eng.analyze_codebase(self.proj)
        self.assertEqual(analysis2["index_stats"]["reindexed"], 0)

    def test_02_pre_modification_context_intelligence(self) -> None:
        self._build_sample_repo()
        mem = HierarchicalMemoryStore(db_path=self.root / "mem.db")
        mem.store_memory(
            tier="project",
            category="architectural_decision",
            title="ADR Pricing Precision",
            content="calculate_discount debe redondear siempre a 2 decimales.",
            provenance="architect",
            project_path=str(self.proj),
        )
        eng = SemanticProjectEngine(db_path=self.root / "pi.db", memory_store=mem)
        ctx = eng.gather_pre_modification_context("core/pricing.py", self.proj)

        self.assertTrue(ctx["ok"])
        self.assertIn("api/routes.py", ctx["affected_dependencies"]["dependent_files"])
        self.assertTrue(
            any(c["consumer_file"] == "api/routes.py" and c["consumer_function"] == "get_price" for c in ctx["consuming_functions"])
        )
        self.assertIn("tests/test_pricing.py", ctx["existing_tests"])
        self.assertTrue(any("Pricing Precision" in d["title"] for d in ctx["prior_architectural_decisions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
