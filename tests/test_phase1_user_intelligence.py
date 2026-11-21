#!/usr/bin/env python3
"""Pruebas unitarias y de integración para Fase 1: User Intelligence & Intent Understanding."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.memory.hierarchical_memory import HierarchicalMemoryStore
from scripts.memory.user_intelligence import UserIntelligenceEngine
from scripts.supervisor.gentle_ai_bridge import IntentUnderstandingEngine, classify_and_route


class TestPhase1UserIntelligence(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory(prefix="saghet_p1_test_")
        self.db_path = Path(self.tmp_dir.name) / "memory.db"
        self.store = HierarchicalMemoryStore(db_path=self.db_path)
        self.user_engine = UserIntelligenceEngine(memory_store=self.store)
        self.intent_engine = IntentUnderstandingEngine(memory_store=self.store, user_engine=self.user_engine)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_01_legacy_schema_migration(self) -> None:
        legacy_db = Path(self.tmp_dir.name) / "legacy.db"
        conn = sqlite3.connect(str(legacy_db))
        conn.execute(
            """
            CREATE TABLE memories (
                id TEXT PRIMARY KEY, tier TEXT NOT NULL, category TEXT NOT NULL,
                title TEXT NOT NULL, content TEXT NOT NULL, provenance TEXT NOT NULL,
                project_path TEXT NOT NULL, session_id TEXT NOT NULL,
                context_json TEXT NOT NULL, confidence REAL NOT NULL,
                fingerprint TEXT NOT NULL, occurrence_count INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, epoch_ms INTEGER NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

        migrated = HierarchicalMemoryStore(db_path=legacy_db)
        res = migrated.store_memory(
            tier="user",
            category="user_preference",
            title="Test",
            content="Preferencia tras migración",
            provenance="test",
        )
        self.assertTrue(res["ok"])
        items = migrated.inspect_memories(tier="user")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "valid")

    def test_02_inferred_isolated_vs_repeated_and_explicit_priority(self) -> None:
        # Observación aislada -> provisional
        r1 = self.user_engine.record_preference(
            preference_key="architecture.simplicity",
            value_description="Preferir módulos pequeños sin abstracciones excesivas.",
            source="inferred",
            scope="permanent",
        )
        self.assertTrue(r1["ok"])
        self.assertEqual(r1["status"], "provisional")

        # Perfil activo sin provisionales no lo promueve aún como preferencia firme
        profile_before = self.user_engine.get_user_profile()
        self.assertEqual(len(profile_before["active_preferences"]), 0)

        # Segunda observación repetida -> se promueve a valid
        r2 = self.user_engine.record_preference(
            preference_key="architecture.simplicity",
            value_description="Preferir módulos pequeños sin abstracciones excesivas.",
            source="inferred",
            scope="permanent",
        )
        self.assertTrue(r2["ok"])
        self.assertEqual(r2["status"], "valid")
        self.assertEqual(r2["occurrence_count"], 2)

        # Preferencia explícita contradice la inferida -> explícita gana y marca la inferida como superseded
        r3 = self.user_engine.record_preference(
            preference_key="architecture.simplicity",
            value_description="Usar arquitectura hexagonal estricta para este proyecto.",
            source="explicit",
            scope="permanent",
        )
        self.assertTrue(r3["ok"])
        self.assertIn(r1["id"], r3["superseded_ids"])

        # Una nueva inferencia contradictoria NO debe sobrescribir la explícita vigente
        r4 = self.user_engine.record_preference(
            preference_key="architecture.simplicity",
            value_description="Usar un único script monolítico.",
            source="inferred",
            scope="permanent",
        )
        self.assertTrue(r4["ok"])
        self.assertTrue(r4.get("ignored_inferred"))

        # Verificar que el recuerdo superseded no se recupera como activo
        active = self.store.retrieve_relevant_memories("arquitectura hexagonal módulos pequeños", tiers=["user"])
        active_ids = {m["id"] for m in active}
        self.assertNotIn(r1["id"], active_ids)
        self.assertIn(r3["id"], active_ids)

    def test_03_temporary_preference_expiration(self) -> None:
        res = self.user_engine.record_preference(
            preference_key="output.format",
            value_description="Usar formato tabla temporalmente.",
            source="explicit",
            scope="temporary",
            valid_until="2020-01-01T00:00:00Z",
        )
        self.assertTrue(res["ok"])
        profile = self.user_engine.get_user_profile()
        self.assertEqual(len(profile["active_preferences"]), 0)

    def test_04_learning_from_corrections_and_natural_capture(self) -> None:
        cap = self.user_engine.detect_and_capture_from_message(
            "Esa solución es demasiado compleja, ya tengo esa funcionalidad en el repo."
        )
        self.assertTrue(cap["captured"])
        self.assertIsNotNone(cap["correction"])
        profile = self.user_engine.get_user_profile()
        keys = {p["key"] for p in profile["active_preferences"]}
        self.assertIn("architecture.simplicity", keys)
        self.assertGreaterEqual(len(profile["recent_corrections"]), 1)

    def test_05_privacy_secrets_and_crud(self) -> None:
        sec_res = self.user_engine.record_preference(
            preference_key="auth.token",
            value_description="Mi api_key=sk-1234567890abcdef123456",
            source="explicit",
        )
        self.assertFalse(sec_res["ok"])

        sens_res = self.user_engine.record_preference(
            preference_key="personal.health",
            value_description="Condición médica privada",
            source="explicit",
            scope="permanent",
            sensitive_authorized=False,
        )
        self.assertFalse(sens_res["ok"])

        # Inspección, corrección y borrado
        pref = self.user_engine.record_preference(
            preference_key="communication.language",
            value_description="Responder en español.",
            source="explicit",
        )
        self.assertTrue(pref["ok"])
        corr = self.user_engine.correct_user_memory(pref["id"], "Responder en español técnico conciso.")
        self.assertTrue(corr["ok"])
        deleted = self.user_engine.delete_user_memory(pref["id"])
        self.assertTrue(deleted["ok"])
        self.assertEqual(len(self.user_engine.inspect_user_model()), 0)

    def test_06_intent_understanding_multilingual_coref_and_clarification(self) -> None:
        # Caso 1: Ambiguo + correferencia sin memoria previa -> debe pedir 1 aclaración
        amb = self.intent_engine.interpret("Hazlo como lo hablamos anteriormente")
        self.assertTrue(amb["has_coreference"])
        self.assertTrue(amb["requires_clarification"])
        self.assertIsNotNone(amb["clarification_question"])

        # Caso 2: Guardamos memoria relevante y repetimos -> ahora resuelve sin preguntar
        self.store.store_memory(
            tier="project",
            category="architectural_decision",
            title="Contrato endpoint /api/health",
            content="Implementar endpoint /api/health en FastAPI devolviendo status ok y latencia.",
            provenance="user:session_prev",
        )
        grounded = self.intent_engine.interpret("Continúa el endpoint health como lo hablamos anteriormente")
        self.assertFalse(grounded["requires_clarification"])
        self.assertGreaterEqual(len(grounded["relevant_memories"]), 1)

        # Caso 3: Informal con abreviaturas/typos en inglés/español -> clasifica sin preguntar
        route = classify_and_route(
            "corrije el bug en la bd sqlite sin romper el endpoint",
            memory_store=self.store,
            user_engine=self.user_engine,
        )
        self.assertEqual(route["primary_specialist"], "database-specialist")
        self.assertEqual(route["intent_analysis"]["task_type"], "debugging")
        self.assertFalse(route["intent_analysis"]["requires_clarification"])
        self.assertGreaterEqual(len(route["intent_analysis"]["explicit_constraints"]), 1)


if __name__ == "__main__":
    unittest.main()
