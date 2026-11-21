#!/usr/bin/env python3
"""Pruebas unitarias para Fase 5: Outcome Learning & Skill Evolution Engine."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.memory.hierarchical_memory import HierarchicalMemoryStore
from scripts.memory.outcome_learning import OutcomeLearningEngine
from scripts.memory.user_intelligence import UserIntelligenceEngine


class TestPhase5OutcomeLearning(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory(prefix="saghet_p5_out_")
        self.root = Path(self.tmp_dir.name)
        self.store = HierarchicalMemoryStore(db_path=self.root / "mem.db")
        self.user_engine = UserIntelligenceEngine(memory_store=self.store)
        self.skills_dir = self.root / "skills"
        self.skills_dir.mkdir(parents=True)
        self.engine = OutcomeLearningEngine(
            memory_store=self.store,
            user_engine=self.user_engine,
            skills_dir=self.skills_dir,
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_01_four_outcome_dimensions_and_feedback_loop(self) -> None:
        # Compila y pasa tests técnicos, pero no cumple expectativa funcional del usuario
        out = self.engine.record_outcome(
            objective="Optimizar consulta SQL",
            strategy="execution",
            model="ollama/qwen3.5:9b",
            specialists=["database-specialist"],
            tools_used=["read", "edit", "bash"],
            attempts=1,
            errors=[],
            technical_success=True,
            functional_success=False,
            project_path="/tmp/proj_x",
            elapsed_s=8.5,
            tokens_used=950,
            token_budget=1792,
        )
        self.assertTrue(out["ok"])
        self.assertTrue(out["dimensions"]["technical_success"])
        self.assertFalse(out["dimensions"]["functional_success"])
        self.assertGreater(out["dimensions"]["execution_efficiency"], 0.8)

        fb = self.engine.record_user_feedback(
            out["outcome_id"],
            accepted=False,
            reason="Faltó índice compuesto en la migración",
        )
        self.assertTrue(fb["ok"])
        self.assertFalse(fb["user_accepted"])
        profile = self.user_engine.get_user_profile(project_path="/tmp/proj_x")
        self.assertEqual(len(profile["rejected_solutions"]), 1)

    def test_02_skill_evolution_gate_dedup_and_rollback(self) -> None:
        # Sin 2 ejecuciones verificadas no debe proponer Skill
        p_fail = self.engine.propose_skill_from_patterns(
            skill_name="sqlite-wal-tuning",
            description="Configura SQLite WAL y verificación de integridad.",
            steps=["Habilitar WAL", "Ejecutar PRAGMA integrity_check"],
            min_verified_outcomes=2,
        )
        self.assertFalse(p_fail["ok"])

        # Registrar 2 ejecuciones técnica y funcionalmente exitosas
        for _ in range(2):
            self.engine.record_outcome(
                objective="Configurar SQLite WAL",
                strategy="execution",
                model="ollama/qwen3.5:9b",
                specialists=["database-specialist"],
                tools_used=["edit", "bash"],
                attempts=1,
                errors=[],
                technical_success=True,
                functional_success=True,
            )

        p_ok = self.engine.propose_skill_from_patterns(
            skill_name="sqlite-wal-tuning",
            description="Configura SQLite WAL y verificación de integridad.",
            steps=["Habilitar WAL", "Ejecutar PRAGMA integrity_check"],
            min_verified_outcomes=2,
        )
        self.assertTrue(p_ok["ok"])

        inst = self.engine.install_and_rollback_skill("sqlite-wal-tuning", p_ok["markdown"], approve=True)
        self.assertTrue(inst["ok"])
        self.assertTrue(Path(inst["path"]).is_file())

        # Detección de duplicado si se vuelve a proponer
        p_dup = self.engine.propose_skill_from_patterns(
            skill_name="sqlite-wal-tuning",
            description="Configura SQLite WAL y verificación de integridad.",
            steps=["Habilitar WAL"],
            min_verified_outcomes=2,
        )
        self.assertFalse(p_dup["ok"])
        self.assertIn("duplicate_of", p_dup)

        # Rollback limpio
        rb = self.engine.install_and_rollback_skill("sqlite-wal-tuning", "", approve=False)
        self.assertTrue(rb["ok"])
        self.assertFalse(Path(inst["path"]).exists())


if __name__ == "__main__":
    unittest.main()
