#!/usr/bin/env python3
"""Pruebas de integración para Fase A: CognitiveBridge (puente vivo pre-turno y post-turno)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.supervisor.cognitive_bridge import CognitiveBridge


class TestPhaseACognitiveBridge(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory(prefix="saghet_pA_bridge_")
        self.root = Path(self.tmp_dir.name)
        self.proj_dir = self.root / "demo_proj"
        self.proj_dir.mkdir(parents=True)
        (self.proj_dir / "service.py").write_text("def ping():\n    return 'pong'\n", encoding="utf-8")
        self.bridge = CognitiveBridge(
            memory_db_path=self.root / "mem.db",
            project_db_path=self.root / "proj.db",
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_01_full_cognitive_turn_lifecycle_and_continuity(self) -> None:
        # Turno 1: el usuario expresa preferencia explícita y pide una tarea
        pre1 = self.bridge.prepare_turn_context(
            objective="Prioriza simplicidad y añade validación en service.py",
            project_path=str(self.proj_dir),
            session_id="sess_1",
        )
        self.assertTrue(pre1["ok"])
        self.assertTrue(pre1["captured_user_signals"]["captured"])
        self.assertFalse(pre1["requires_clarification"])
        self.assertIn("[COGNITIVE_PLAN]", pre1["compact_context_prompt"])

        # Finalizar turno 1 con éxito verificado y avance de continuidad
        fin1 = self.bridge.finalize_turn_outcome(
            objective="Añadir validación en service.py",
            strategy=pre1["routing"]["reasoning_plan"]["strategy"],
            model=pre1["routing"]["selected_model"],
            specialists=[pre1["routing"]["primary_specialist"]],
            tools_used=["read", "edit", "bash"],
            attempts=1,
            errors=[],
            technical_success=True,
            functional_success=True,
            project_path=str(self.proj_dir),
            completed_feature="Validación en service.py",
            next_recommended_step="Agregar pruebas unitarias para service.py",
        )
        self.assertTrue(fin1["ok"])
        self.assertTrue(fin1["outcome"]["dimensions"]["technical_success"])

        # Turno 2 (nueva sesión): el usuario dice "continuemos" -> reconstruye continuidad y recuerda preferencia
        pre2 = self.bridge.prepare_turn_context(
            objective="Continuemos con el proyecto",
            project_path=str(self.proj_dir),
            session_id="sess_2",
        )
        self.assertIsNotNone(pre2["continuity"])
        self.assertTrue(pre2["continuity"]["has_saved_state"])
        self.assertIn("Validación en service.py", pre2["continuity"]["completed_features"])
        self.assertIn("[PROJECT_CONTINUITY]", pre2["compact_context_prompt"])


if __name__ == "__main__":
    unittest.main()
