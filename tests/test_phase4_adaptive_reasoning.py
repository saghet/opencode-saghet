#!/usr/bin/env python3
"""Pruebas unitarias para Fase 4: Adaptive Reasoning Engine y planificación DAG adaptativa."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.memory.hierarchical_memory import HierarchicalMemoryStore
from scripts.memory.user_intelligence import UserIntelligenceEngine
from scripts.supervisor.gentle_ai_bridge import classify_and_route
from scripts.supervisor.quality_supervisor import QualitySupervisor, TaskDependencyDAG


class TestPhase4AdaptiveReasoning(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory(prefix="saghet_p4_reason_")
        self.store = HierarchicalMemoryStore(db_path=Path(self.tmp_dir.name) / "mem.db")
        self.user_engine = UserIntelligenceEngine(memory_store=self.store)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_01_simple_query_avoids_unnecessary_dag(self) -> None:
        route = classify_and_route(
            "Lista brevemente los archivos de configuración",
            memory_store=self.store,
            user_engine=self.user_engine,
        )
        rp = route["reasoning_plan"]
        self.assertFalse(rp["use_dag"])
        self.assertEqual(rp["execution_cost"], "low")
        self.assertLessEqual(rp["token_budget"], 1024)

        sup = QualitySupervisor(max_iterations=3)
        plan = sup.plan_execution("Lista brevemente los archivos de configuración")
        self.assertEqual(len(plan["dag"]["tasks"]), 1)

    def test_02_architectural_security_uses_dag_and_dependency_analysis(self) -> None:
        route = classify_and_route(
            "Diseña la arquitectura de autenticación CSRF, token y migración de esquema SQL en backend",
            memory_store=self.store,
            user_engine=self.user_engine,
        )
        rp = route["reasoning_plan"]
        self.assertTrue(rp["use_dag"])
        self.assertTrue(rp["requires_dependency_analysis"])
        self.assertEqual(rp["impact"], "high")
        self.assertGreaterEqual(rp["token_budget"], 2560)
        self.assertTrue(route["worktree_required"])

    def test_03_ambiguous_coreference_selects_clarification_strategy(self) -> None:
        route = classify_and_route(
            "Hazlo como lo hablamos anteriormente",
            memory_store=self.store,
            user_engine=self.user_engine,
        )
        rp = route["reasoning_plan"]
        self.assertEqual(rp["strategy"], "clarification")
        self.assertFalse(rp["use_dag"])

    def test_04_dag_replan_after_failure(self) -> None:
        dag = TaskDependencyDAG()
        dag.add_task("step1_impl", "Implementar", "senior-developer")
        dag.add_task("step2_qa", "QA", "qa-engineer", dependencies=["step1_impl"])
        dag.nodes["step1_impl"].status = "FAILED"
        dag.refresh_states()
        self.assertEqual(dag.nodes["step2_qa"].status, "BLOCKED")

        replan = dag.replan_after_failure("step1_impl", recovery_specialist="backend-specialist", reason="Error de import")
        self.assertTrue(replan["ok"])
        self.assertIn("step2_qa", replan["relinked_tasks"])
        self.assertEqual(dag.nodes["step1_impl_recovery"].status, "READY")
        self.assertEqual(dag.nodes["step2_qa"].status, "PENDING")


if __name__ == "__main__":
    unittest.main()
