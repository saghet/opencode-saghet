#!/usr/bin/env python3
"""Pruebas unitarias y de integración para Fase 2: Semantic Memory Engine."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.memory.hierarchical_memory import HierarchicalMemoryStore


class TestPhase2SemanticMemory(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory(prefix="saghet_p2_mem_")
        self.db_path = Path(self.tmp_dir.name) / "memory.db"
        self.store = HierarchicalMemoryStore(db_path=self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_01_hybrid_bilingual_semantic_retrieval(self) -> None:
        # Guardamos un recuerdo en español sin usar las palabras exactas en inglés de la consulta
        r_auth = self.store.store_memory(
            tier="project",
            category="architectural_decision",
            title="Control de acceso en API local",
            content="Validar sesion mediante cabecera segura y renovacion periodica.",
            provenance="architect:api",
            project_path="/tmp/proj_a",
            context={"tags": ["seguridad", "acceso"]},
            confidence=0.92,
            importance=0.85,
        )
        self.assertTrue(r_auth["ok"])

        # Consulta semánticamente equivalente en inglés ("authentication login jwt")
        hits = self.store.retrieve_relevant_memories(
            query="authentication login jwt",
            project_path="/tmp/proj_a",
            tiers=["project"],
            min_relevance=0.14,
        )
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0]["id"], r_auth["id"])

    def test_02_project_isolation_and_superseded_filtering(self) -> None:
        r_a = self.store.store_memory(
            tier="project",
            category="architectural_decision",
            title="Base de datos proyecto A",
            content="Usar SQLite WAL para proyecto A.",
            provenance="architect:a",
            project_path="/tmp/proj_a",
        )
        r_b = self.store.store_memory(
            tier="project",
            category="architectural_decision",
            title="Base de datos proyecto B",
            content="Usar PostgreSQL para proyecto B.",
            provenance="architect:b",
            project_path="/tmp/proj_b",
        )
        self.store.invalidate_memory(r_a["id"], reason="Obsoleta", new_status="superseded")

        hits_a = self.store.retrieve_relevant_memories("database sqlite", project_path="/tmp/proj_a", tiers=["project"])
        self.assertEqual(len(hits_a), 0)

        hits_b = self.store.retrieve_relevant_memories("database postgres", project_path="/tmp/proj_b", tiers=["project"])
        self.assertEqual(len(hits_b), 1)
        self.assertEqual(hits_b[0]["id"], r_b["id"])

    def test_03_memory_relations_and_contextual_pack(self) -> None:
        m1 = self.store.store_memory(
            tier="project",
            category="architectural_decision",
            title="Politica VRAM 8GB",
            content="OLLAMA_MAX_LOADED_MODELS=1 para evitar swap en RTX 4060.",
            provenance="system",
            project_path="/tmp/proj_a",
            confidence=0.95,
        )
        m2 = self.store.store_memory(
            tier="experience",
            category="proven_solution",
            title="Serializacion de subagentes",
            content="Ejecutar un subagente GPU a la vez evita colas zombi en puerto 11434.",
            provenance="supervisor:qa",
            project_path="/tmp/proj_a",
            confidence=0.90,
        )
        link_res = self.store.link_memories(m1["id"], m2["id"], relation_type="supports")
        self.assertTrue(link_res["ok"])

        pack = self.store.build_contextual_memory_pack(
            objective="optimizar vram y subagentes ollama",
            project_path="/tmp/proj_a",
            max_chars=500,
        )
        self.assertLessEqual(pack["char_count"], 500)
        self.assertGreaterEqual(pack["included_count"], 1)
        self.assertIn("OLLAMA_MAX_LOADED_MODELS=1", pack["context_text"])

    def test_04_experience_consolidation(self) -> None:
        # Dos ejecuciones verificadas repetidas -> se consolidan en procedimiento reutilizable
        for _ in range(2):
            self.store.store_memory(
                tier="experience",
                category="verified_execution",
                title="Compilacion y test suite Python",
                content="Ejecutar python3 -m unittest discover antes de hacer merge del worktree.",
                provenance="supervisor:qa-engineer",
                project_path="/tmp/proj_a",
                context={"tags": ["qa", "unittest"]},
                confidence=0.94,
            )

        cons = self.store.consolidate_experiences(project_path="/tmp/proj_a", min_occurrences=2)
        self.assertTrue(cons["ok"])
        self.assertEqual(cons["consolidated_count"], 1)

        proc = self.store.inspect_memories(category="consolidated_procedure", project_path="/tmp/proj_a")
        self.assertEqual(len(proc), 1)
        self.assertIn("consolidation:", proc[0]["provenance"])


if __name__ == "__main__":
    unittest.main()
