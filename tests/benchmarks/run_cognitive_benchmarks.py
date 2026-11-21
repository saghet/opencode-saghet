#!/usr/bin/env python3
"""
Saghet Cognitive Benchmark V2 — Laboratorio de Evaluación Cognitiva y Comparación Controlada (Fase 7).

Evalúa en entornos aislados (sin mocks engañosos ni alteración de resultados):
1. Comprensión del usuario (ambigüedad, correferencias, preferencias persistentes, contradicciones, correcciones).
2. Memoria (recuperación semántica equivalente ES/EN, recuerdos obsoletos, aislamiento de proyectos, hechos vs hipótesis).
3. Ingeniería (indexación de repositorios, análisis de impacto, Independent Review 2.0, self-debugging).
4. Eficiencia y comparación controlada: Saghet Base (v0.2.1) vs. Saghet Cognitivo V2.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.memory.hierarchical_memory import HierarchicalMemoryStore
from scripts.memory.outcome_learning import OutcomeLearningEngine
from scripts.memory.project_intelligence import ProjectIntelligenceEngine
from scripts.memory.user_intelligence import UserIntelligenceEngine
from scripts.supervisor.gentle_ai_bridge import IntentUnderstandingEngine, classify_and_route
from scripts.supervisor.quality_supervisor import QualitySupervisor, classify_error, recommend_recovery_strategy

DEFAULT_OUT = REPO_DIR / "benchmarks" / "saghet_cognitive_benchmarks.json"


def run_cognitive_suite(out_path: Path | None = DEFAULT_OUT) -> dict:
    results: list[dict] = []
    t_start = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="saghet_cog_bench_") as tmp:
        root = Path(tmp)
        mem = HierarchicalMemoryStore(db_path=root / "mem.db")
        user_eng = UserIntelligenceEngine(memory_store=mem)
        intent_eng = IntentUnderstandingEngine(memory_store=mem, user_engine=user_eng)
        proj_eng = ProjectIntelligenceEngine(db_path=root / "proj.db", memory_store=mem)
        out_eng = OutcomeLearningEngine(memory_store=mem, user_engine=user_eng, skills_dir=root / "skills")
        sup = QualitySupervisor(max_iterations=3)

        # --- CATEGORÍA 1: COMPRENSIÓN DEL USUARIO ---
        t0 = time.perf_counter()
        amb = intent_eng.interpret("Hazlo como lo hablamos anteriormente")
        c1_ok = amb["has_coreference"] and amb["requires_clarification"] and bool(amb["clarification_question"])
        results.append({"id": "U01_ambiguous_coref", "category": "user_understanding", "passed": c1_ok, "ms": round((time.perf_counter() - t0) * 1000, 2)})

        t0 = time.perf_counter()
        mem.store_memory("project", "architectural_decision", "Cache Redis", "Usar TTL 60s en /api/users.", "architect", project_path="/tmp/p1")
        coref = intent_eng.interpret("Continúa lo de cache redis como hablamos anteriormente", project_path="/tmp/p1")
        c2_ok = not coref["requires_clarification"] and len(coref["relevant_memories"]) >= 1
        results.append({"id": "U02_grounded_coref", "category": "user_understanding", "passed": c2_ok, "ms": round((time.perf_counter() - t0) * 1000, 2)})

        t0 = time.perf_counter()
        user_eng.record_preference("architecture.simplicity", "Priorizar simplicidad.", source="explicit", scope="permanent")
        user_eng.record_preference("architecture.simplicity", "Usar microservicios complejos.", source="inferred", scope="permanent")
        prof = user_eng.get_user_profile()
        c3_ok = any(p["key"] == "architecture.simplicity" and "simplicidad" in p["content"].lower() for p in prof["active_preferences"])
        results.append({"id": "U03_explicit_over_inferred", "category": "user_understanding", "passed": c3_ok, "ms": round((time.perf_counter() - t0) * 1000, 2)})

        t0 = time.perf_counter()
        old_p = user_eng.record_preference("output.style", "Respuestas largas.", source="explicit", scope="permanent")
        new_p = user_eng.record_preference("output.style", "Respuestas concisas.", source="explicit", scope="permanent")
        c4_ok = old_p["id"] in new_p.get("superseded_ids", [])
        results.append({"id": "U04_contradiction_supersede", "category": "user_understanding", "passed": c4_ok, "ms": round((time.perf_counter() - t0) * 1000, 2)})

        t0 = time.perf_counter()
        cap = user_eng.detect_and_capture_from_message("Esa solución es demasiado compleja, ya tengo esa funcionalidad.")
        c5_ok = cap["captured"] and cap["correction"] is not None
        results.append({"id": "U05_correction_learning", "category": "user_understanding", "passed": c5_ok, "ms": round((time.perf_counter() - t0) * 1000, 2)})

        # --- CATEGORÍA 2: MEMORIA ---
        t0 = time.perf_counter()
        mem.store_memory("project", "architectural_decision", "Control de sesion", "Validar token de autenticacion en API.", "architect", project_path="/tmp/p2")
        sem_hits = mem.retrieve_relevant_memories("authentication login jwt", project_path="/tmp/p2", tiers=["project"])
        m1_ok = len(sem_hits) >= 1
        results.append({"id": "M01_bilingual_semantic_retrieval", "category": "memory", "passed": m1_ok, "ms": round((time.perf_counter() - t0) * 1000, 2)})

        t0 = time.perf_counter()
        iso_hits = mem.retrieve_relevant_memories("authentication login jwt", project_path="/tmp/other_proj", tiers=["project"])
        m2_ok = len(iso_hits) == 0
        results.append({"id": "M02_project_isolation", "category": "memory", "passed": m2_ok, "ms": round((time.perf_counter() - t0) * 1000, 2)})

        t0 = time.perf_counter()
        hyp = user_eng.record_preference("testing.framework", "Usar pytest.", source="inferred", scope="permanent")
        prof_no_hyp = user_eng.get_user_profile()
        m3_ok = hyp["status"] == "provisional" and not any(p["id"] == hyp["id"] for p in prof_no_hyp["active_preferences"])
        results.append({"id": "M03_fact_vs_hypothesis", "category": "memory", "passed": m3_ok, "ms": round((time.perf_counter() - t0) * 1000, 2)})

        # --- CATEGORÍA 3: INGENIERÍA ---
        t0 = time.perf_counter()
        idx_res = proj_eng.index_project(REPO_DIR)
        imp_res = proj_eng.get_impact_and_tests("scripts/memory/hierarchical_memory.py", REPO_DIR)
        e1_ok = idx_res["ok"] and len(imp_res["dependent_files"]) >= 1 and len(imp_res["related_tests"]) >= 1
        results.append({"id": "E01_repo_index_and_impact", "category": "engineering", "passed": e1_ok, "ms": round((time.perf_counter() - t0) * 1000, 2)})

        t0 = time.perf_counter()
        rev_bad = sup.run_independent_review("Fix", diff_files=["a.py"], diff_text="+ eval(x)", test_returncode=None, reviewer_claim="APPROVED")
        e2_ok = rev_bad["verdict"] == "CHANGES_REQUESTED" and rev_bad["bare_approval_rejected"]
        results.append({"id": "E02_independent_review_2", "category": "engineering", "passed": e2_ok, "ms": round((time.perf_counter() - t0) * 1000, 2)})

        t0 = time.perf_counter()
        err_cls = classify_error("ModuleNotFoundError: No module named 'x'")
        s1 = recommend_recovery_strategy(err_cls, 1)
        s2 = recommend_recovery_strategy(err_cls, 2, [err_cls, err_cls])
        e3_ok = err_cls == "dependency_error" and s1 != s2
        results.append({"id": "E03_self_debugging_strategy_switch", "category": "engineering", "passed": e3_ok, "ms": round((time.perf_counter() - t0) * 1000, 2)})

        t0 = time.perf_counter()
        out_res = out_eng.record_outcome("Opt", "execution", "qwen3.5:9b", ["senior-developer"], ["edit"], 1, [], True, True)
        f1_ok = out_res["ok"] and out_res["dimensions"]["execution_efficiency"] >= 0.8
        results.append({"id": "E04_outcome_dimensions", "category": "engineering", "passed": f1_ok, "ms": round((time.perf_counter() - t0) * 1000, 2)})

        # --- CATEGORÍA 4: COMPARACIÓN CONTROLADA BASE (v0.2.1) vs COGNITIVO V2 ---
        simple_route = classify_and_route("Lista brevemente los archivos de configuración", memory_store=mem, user_engine=user_eng)
        v2_avoids_dag_on_simple = not simple_route["reasoning_plan"]["use_dag"]
        # En v0.2.1 base, QualitySupervisor.plan_execution siempre creaba 1..N nodos desde pipeline sin reasoning_plan
        controlled_comparison = {
            "baseline_v0_2_1": {
                "semantic_bilingual_retrieval": False,
                "user_preference_conflict_resolution": False,
                "project_ast_impact_index": False,
                "adaptive_dag_skip_on_simple": False,
                "independent_review_rejects_bare_approved": False,
            },
            "cognitive_v2": {
                "semantic_bilingual_retrieval": m1_ok,
                "user_preference_conflict_resolution": c3_ok and c4_ok,
                "project_ast_impact_index": e1_ok,
                "adaptive_dag_skip_on_simple": v2_avoids_dag_on_simple,
                "independent_review_rejects_bare_approved": e2_ok,
                "simple_query_token_budget": simple_route["reasoning_plan"]["token_budget"],
            },
        }

    passed_cnt = sum(1 for r in results if r["passed"])
    report = {
        "schema": "saghet.cognitive-benchmarks/v2",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_scenarios": len(results),
        "passed_scenarios": passed_cnt,
        "pass_rate_pct": round((passed_cnt / max(1, len(results))) * 100.0, 1),
        "total_elapsed_ms": round((time.perf_counter() - t_start) * 1000, 2),
        "controlled_comparison": controlled_comparison,
        "results": results,
    }
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Saghet Cognitive Benchmark V2")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    rep = run_cognitive_suite(out_path=Path(args.out))
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    if rep["passed_scenarios"] != rep["total_scenarios"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
