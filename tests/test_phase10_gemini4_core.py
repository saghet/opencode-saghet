#!/usr/bin/env python3
"""Pruebas unitarias para Fase 1 / Etapa 2: Gemini 4 Neon Intelligence Core."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.eval.model_lab import SmartModelRouter
from scripts.intelligence.gemini_core import (
    FileOwnershipCoordinator,
    Gemini4NeonCoordinator,
    OFFICIAL_GEMINI_MODELS,
    QuotaBudget,
    RetryPolicy,
)
from scripts.memory.hierarchical_memory import HierarchicalMemoryStore


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._bytes = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._bytes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestPhase10Gemini4Core(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_01_official_catalog_and_model_switching(self) -> None:
        self.assertIn("gemini-4-neon", OFFICIAL_GEMINI_MODELS)
        self.assertEqual(OFFICIAL_GEMINI_MODELS["gemini-4-neon"]["opencode_id"], "google/gemini-4-neon")
        self.assertEqual(OFFICIAL_GEMINI_MODELS["gemini-4-neon"]["context_tokens"], 1_048_576)

        coord = Gemini4NeonCoordinator(api_key="", ledger_path=self.root / "dec.jsonl")
        self.assertEqual(coord.active_model, "google/gemini-4-neon")

        # Rechazar identificadores inventados
        bad = coord.set_active_model("google/gemini-99-invented")
        self.assertFalse(bad["ok"])

        # Permitir cambiar a otro modelo oficial o local Ollama sin alterar el núcleo
        sw1 = coord.set_active_model("google/gemini-4-carbon", reason="deep_logic")
        self.assertTrue(sw1["ok"])
        self.assertEqual(coord.active_model, "google/gemini-4-carbon")

        sw2 = coord.set_active_model("ollama/qwen3.5:9b", reason="offline_mode")
        self.assertTrue(sw2["ok"])
        self.assertEqual(coord.active_model, "ollama/qwen3.5:9b")
        self.assertGreaterEqual(len(coord.get_recent_decisions()), 2)

    def test_02_verify_model_availability_and_retries(self) -> None:
        calls = {"count": 0}

        def fake_opener(req, timeout=10.0):
            calls["count"] += 1
            url = req.full_url
            if "/models?" in url:
                return _FakeHTTPResponse(
                    {"models": [{"name": "models/gemini-4-neon"}, {"name": "models/gemini-4-hydrogen"}]}
                )
            if calls["count"] == 2:
                raise urllib.error.HTTPError(url, 429, "Too Many Requests", hdrs={}, fp=io.BytesIO(b""))
            return _FakeHTTPResponse(
                {
                    "candidates": [{"content": {"parts": [{"text": '{"plan":"modular"}'}]}}],
                    "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 40, "totalTokenCount": 160},
                }
            )

        coord = Gemini4NeonCoordinator(
            model_id="google/gemini-4-neon",
            api_key="test-fake-key-value",
            retry_policy=RetryPolicy(max_retries=2, base_delay_s=0.01),
            ledger_path=self.root / "dec2.jsonl",
            http_opener=fake_opener,
            sleep_fn=lambda _: None,
        )
        probe = coord.verify_model_availability("gemini-4-neon")
        self.assertTrue(probe["ok"] and probe["available"])
        self.assertIn("gemini-4-neon", probe["available_models"])

        res = coord.generate("Diseña arquitectura", thinking_level="high", allow_local_fallback=False)
        self.assertTrue(res["ok"])
        self.assertEqual(res["model_used"], "google/gemini-4-neon")
        self.assertEqual(res["attempts"], 2)  # 1er intento 429, 2do éxito
        self.assertEqual(res["usage"]["total_tokens"], 160)
        self.assertEqual(coord.quota.snapshot()["tokens_used_session"], 160)

    def test_03_quota_enforcement_and_graceful_fallback(self) -> None:
        quota = QuotaBudget(max_requests_per_minute=1, max_tokens_per_session=10)
        coord = Gemini4NeonCoordinator(
            model_id="google/gemini-4-neon",
            api_key="test-key",
            quota=quota,
            ledger_path=self.root / "dec3.jsonl",
        )
        res = coord.generate("Un prompt de mas de cien caracteres para exceder la cuota de diez tokens " * 3, allow_local_fallback=False)
        self.assertFalse(res["ok"])
        self.assertIn("token_quota_exceeded", res["error"])
        self.assertTrue(res["recommended_fallback"].startswith("ollama/"))

    def test_04_selective_context_blocks_secrets_and_respects_budget(self) -> None:
        mem = HierarchicalMemoryStore(db_path=self.root / "mem.db")
        mem.store_memory(
            tier="project",
            category="architectural_decision",
            title="ADR API REST",
            content="Usar FastAPI para capa API manteniendo dominio desacoplado.",
            provenance="architect",
            project_path=str(self.root),
        )
        coord = Gemini4NeonCoordinator(api_key="", memory_store=mem, ledger_path=self.root / "dec4.jsonl")
        ctx = coord.assemble_selective_context(
            objective="Diseñar API REST desacoplada",
            project_path=self.root,
            candidate_files=[
                {"rel_path": "core/domain.py", "score": 9.5, "snippet": "def calculate_tax(amount): return amount * 0.19"},
                {"rel_path": "config/leaked.py", "score": 10.0, "snippet": "API_KEY = 'AIzaSyFakeSecretValue123456789012345'"},
                {"rel_path": "docs/huge.md", "score": 1.0, "snippet": "X" * 5000},
            ],
            max_chars=1800,
        )
        self.assertTrue(ctx["selective_retrieval"])
        self.assertIn("core/domain.py", ctx["included_files"])
        self.assertTrue(any("blocked:secret" in s for s in ctx["skipped_files"]))
        self.assertLessEqual(ctx["chars_used"], 1800)
        self.assertIn("FastAPI", ctx["context_text"])

    def test_05_file_ownership_prevents_contradictory_edits(self) -> None:
        own = FileOwnershipCoordinator()
        c1 = own.claim_files("task_1", "backend-specialist", write_files=["app/service.py"])
        self.assertTrue(c1["ok"])
        c2 = own.claim_files("task_2", "senior-developer", write_files=["app/service.py"])
        self.assertFalse(c2["ok"])
        self.assertEqual(c2["conflicts"][0]["type"], "write_write_conflict")
        own.release_task("task_1")
        c3 = own.claim_files("task_2", "senior-developer", write_files=["app/service.py"])
        self.assertTrue(c3["ok"])

        plan_conflicts = own.detect_plan_conflicts(
            [
                {"id": "t1", "write_files": ["src/app.py"], "dependencies": []},
                {"id": "t2", "write_files": ["src/app.py"], "dependencies": []},
                {"id": "t3", "write_files": ["src/app.py"], "dependencies": ["t1"]},
            ]
        )
        pairs = [{c["task_a"], c["task_b"]} for c in plan_conflicts]
        self.assertIn({"t1", "t2"}, pairs)
        self.assertIn({"t2", "t3"}, pairs)
        self.assertNotIn({"t1", "t3"}, pairs)

    def test_06_smart_model_router_hybrid_gemini_and_local_preserved(self) -> None:
        router = SmartModelRouter()
        r_gem_arch = router.route("architecture", gemini_coordinator_available=True)
        self.assertEqual(r_gem_arch["selected_model"], "google/gemini-4-neon")
        self.assertIn("ollama/qwen3.5:9b", r_gem_arch["fallback_chain"])

        r_gem_code = router.route("coding", gemini_coordinator_available=True)
        self.assertEqual(r_gem_code["selected_model"], "google/gemini-4-argon")

        r_gem_sec = router.route("security_audit", gemini_coordinator_available=True)
        self.assertEqual(r_gem_sec["selected_model"], "google/gemini-4-argon")

        r_gem_cls = router.route("classification", gemini_coordinator_available=True)
        self.assertEqual(r_gem_cls["selected_model"], "google/gemini-4-hydrogen")

        self.assertEqual(Gemini4NeonCoordinator.select_model_for_specialty("coding"), "google/gemini-4-argon")
        self.assertEqual(Gemini4NeonCoordinator.select_model_for_specialty("classification"), "google/gemini-4-hydrogen")

        r_loc = router.route("architecture", loaded_in_vram=["qwen3.5:9b"], gemini_coordinator_available=False)
        self.assertEqual(r_loc["selected_model"], "ollama/qwen3.5:9b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
