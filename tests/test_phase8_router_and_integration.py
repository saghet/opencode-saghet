#!/usr/bin/env python3
"""Pruebas unitarias para Fase 8: SmartModelRouter 2.0 y alineación de diagnóstico."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.eval.model_lab import SmartModelRouter, compute_verifiable_score
from scripts.supervisor.session_diagnostics import KNOWN_AGENT_NAMES


class TestPhase8RouterAndAlignment(unittest.TestCase):
    def test_01_unknown_metrics_reported_explicitly(self) -> None:
        res_unknown = compute_verifiable_score({}, specialty="coding")
        self.assertIsNone(res_unknown["verifiable_score"])
        self.assertEqual(res_unknown["evaluation_status"], "unknown")
        self.assertGreater(len(res_unknown["unknown_metrics"]), 0)

        res_partial = compute_verifiable_score({"code_quality_score": 85.0}, specialty="coding")
        self.assertEqual(res_partial["evaluation_status"], "partial")
        self.assertIn("test_pass_rate_pct", res_partial["unknown_metrics"])

    def test_02_vram_swap_hysteresis_keeps_resident_model(self) -> None:
        router = SmartModelRouter()
        # Si qwen3.5:9b ya está cargado en VRAM y la diferencia con rana:9b en independent_review es <= 5.0 pts,
        # mantiene qwen3.5:9b para evitar el swap de ~4-6s en RTX 4060 (MAX_LOADED_MODELS=1).
        decision = router.route(
            "independent_review",
            loaded_in_vram=["qwen3.5:9b"],
            avoid_vram_swap=True,
        )
        self.assertEqual(decision["selected_model"], "ollama/qwen3.5:9b")
        self.assertTrue(decision["vram_swap_avoided"])

    def test_03_known_agent_names_aligned(self) -> None:
        self.assertIn("database-specialist", KNOWN_AGENT_NAMES)
        self.assertIn("documentation-engineer", KNOWN_AGENT_NAMES)
        self.assertIn("fast-helper", KNOWN_AGENT_NAMES)


if __name__ == "__main__":
    unittest.main()
