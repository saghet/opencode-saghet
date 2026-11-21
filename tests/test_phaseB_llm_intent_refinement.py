#!/usr/bin/env python3
"""Pruebas unitarias para Fase B: Refinamiento Semántico LLM Opcional con fallback determinista."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.memory.hierarchical_memory import HierarchicalMemoryStore
from scripts.memory.user_intelligence import UserIntelligenceEngine
from scripts.supervisor.gentle_ai_bridge import IntentUnderstandingEngine


class TestPhaseBLLMIntentRefinement(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory(prefix="saghet_pB_llm_")
        self.store = HierarchicalMemoryStore(db_path=Path(self.tmp_dir.name) / "mem.db")
        self.user_engine = UserIntelligenceEngine(memory_store=self.store)
        self.engine = IntentUnderstandingEngine(memory_store=self.store, user_engine=self.user_engine)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_01_high_confidence_skips_llm_call(self) -> None:
        with patch.object(IntentUnderstandingEngine, "_refine_with_llm") as mock_llm:
            res = self.engine.interpret(
                "Implementa validación CSRF y pruebas unitarias en server.py",
                use_llm=True,
            )
            mock_llm.assert_not_called()
            self.assertFalse(res["llm_refined"])

    def test_02_borderline_confidence_graceful_fallback_when_ollama_offline(self) -> None:
        # Simula Ollama desconectado para validar el fallback determinista
        with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("offline")):
            res = self.engine.interpret("mejora esto", use_llm=True)
            self.assertFalse(res["llm_refined"])
            self.assertIn("underspecified_target", res["ambiguities"])

    def test_03_borderline_confidence_refines_when_llm_returns_valid_json(self) -> None:
        with patch.object(
            IntentUnderstandingEngine,
            "_refine_with_llm",
            return_value={
                "task_type": "debugging",
                "desired_outcome": "Diagnosticar y corregir fallo de conexión en módulo activo",
                "requires_clarification": False,
                "clarification_question": None,
            },
        ):
            res = self.engine.interpret("revisa eso", use_llm=True)
            self.assertTrue(res["llm_refined"])
            self.assertEqual(res["task_type"], "debugging")
            self.assertFalse(res["requires_clarification"])


if __name__ == "__main__":
    unittest.main()
