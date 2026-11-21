#!/usr/bin/env python3
"""
Continuous Improvement Engine & Experiment Registry — OpenCode-Saghet (Fase 8).

Analiza experiencias acumuladas (outcome_records) para detectar oportunidades reales de mejora
en skills, prompts, estrategias, enrutamiento, recuperación de errores, indexación o memoria.
Registra experimentos con hipótesis, prueba controlada, métricas antes/después, impacto en recursos
y decisión de aceptación/rechazo, bloqueando mutaciones autónomas sobre políticas de seguridad.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable

from scripts.memory.outcome_learning import OutcomeLearningEngine

SAGHET_STATE_DIR = Path.home() / ".local" / "share" / "opencode-saghet"
DEFAULT_EXPERIMENTS_DB = SAGHET_STATE_DIR / "experiment_registry.db"

VALID_TARGETS = {"skill", "prompt", "strategy", "routing", "error_recovery", "indexing", "memory"}
PROTECTED_TARGETS = {"security_policy", "permissions", "p0_hardening", "opencode_core", "auth_token"}
VALID_DECISIONS = {"PROPOSED", "TESTING", "ACCEPTED", "REJECTED", "ROLLED_BACK"}


class ExperimentRegistry:
    """Registro científico de experimentos y mejora continua basada en evidencia."""

    def __init__(
        self,
        db_path: Path | None = None,
        outcome_engine: OutcomeLearningEngine | None = None,
    ) -> None:
        self.db_path = Path(db_path or DEFAULT_EXPERIMENTS_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.outcome_engine = outcome_engine
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return contextlib.closing(conn)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    target_component TEXT NOT NULL,
                    problem_detected TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    proposed_change TEXT NOT NULL,
                    controlled_test TEXT NOT NULL,
                    before_metrics_json TEXT NOT NULL DEFAULT '{}',
                    after_metrics_json TEXT NOT NULL DEFAULT '{}',
                    resource_impact_json TEXT NOT NULL DEFAULT '{}',
                    decision TEXT NOT NULL DEFAULT 'PROPOSED',
                    decision_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        try:
            os.chmod(self.db_path, 0o600)
        except Exception:
            pass

    def propose_experiment(
        self,
        target_component: str,
        problem_detected: str,
        evidence: str,
        hypothesis: str,
        proposed_change: str,
        controlled_test: str,
        before_metrics: dict | None = None,
        authorized: bool = False,
    ) -> dict:
        """Registra una propuesta de experimento, bloqueando cambios no autorizados en seguridad/núcleo."""
        target = (target_component or "").strip().lower()
        if target in PROTECTED_TARGETS and not authorized:
            return {
                "ok": False,
                "blocked": True,
                "error": f"Bloqueado por seguridad: '{target}' requiere autorización explícita del usuario.",
            }
        if target not in VALID_TARGETS and not authorized:
            return {"ok": False, "error": f"Componente objetivo inválido: '{target}'."}

        exp_id = f"exp_{uuid.uuid4().hex[:10]}"
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO experiments (
                    id, target_component, problem_detected, evidence, hypothesis,
                    proposed_change, controlled_test, before_metrics_json,
                    decision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, ?)
                """,
                (
                    exp_id,
                    target,
                    problem_detected.strip(),
                    evidence.strip(),
                    hypothesis.strip(),
                    proposed_change.strip(),
                    controlled_test.strip(),
                    json.dumps(before_metrics or {}, ensure_ascii=False),
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()
        return {"ok": True, "id": exp_id, "decision": "PROPOSED", "created_at": now_iso}

    def evaluate_experiment(
        self,
        exp_id: str,
        after_metrics: dict,
        resource_impact: dict | None = None,
        primary_metric: str = "score",
        higher_is_better: bool = True,
        max_regression_tolerance: float = 0.0,
    ) -> dict:
        """Compara métricas antes/después de una prueba controlada y decide ACCEPTED o REJECTED."""
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM experiments WHERE id = ?", (exp_id,)).fetchone()
            if row is None:
                return {"ok": False, "error": f"Experimento no encontrado: {exp_id}"}

            before = json.loads(row["before_metrics_json"] or "{}")
            b_val = float(before.get(primary_metric, 0.0))
            a_val = float(after_metrics.get(primary_metric, 0.0))
            delta = (a_val - b_val) if higher_is_better else (b_val - a_val)

            passed_tests = bool(after_metrics.get("tests_passed", True))
            if passed_tests and delta > -max_regression_tolerance and a_val != b_val and delta > 0:
                decision = "ACCEPTED"
                reason = f"Mejora verificada en '{primary_metric}': {b_val} -> {a_val} (delta={round(delta, 3)})."
            else:
                decision = "REJECTED"
                reason = f"Sin mejora verificable o regresión en '{primary_metric}': {b_val} -> {a_val} (tests_passed={passed_tests})."

            conn.execute(
                """
                UPDATE experiments
                SET after_metrics_json = ?, resource_impact_json = ?, decision = ?, decision_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(after_metrics, ensure_ascii=False),
                    json.dumps(resource_impact or {}, ensure_ascii=False),
                    decision,
                    reason,
                    now_iso,
                    exp_id,
                ),
            )
            conn.commit()
        return {"ok": True, "id": exp_id, "decision": decision, "reason": reason, "delta": round(delta, 4)}

    def rollback_experiment(self, exp_id: str, reason: str = "Regresión detectada") -> dict:
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE experiments SET decision = 'ROLLED_BACK', decision_reason = ?, updated_at = ? WHERE id = ?",
                (reason, now_iso, exp_id),
            )
            conn.commit()
            if cur.rowcount == 0:
                return {"ok": False, "error": f"Experimento no encontrado: {exp_id}"}
        return {"ok": True, "id": exp_id, "decision": "ROLLED_BACK", "reason": reason}

    def run_controlled_command(
        self,
        exp_id: str,
        command: list[str],
        cwd: Path,
        timeout: float = 30.0,
    ) -> dict:
        """Ejecuta una prueba controlada aislada para un experimento registrado."""
        t0 = time.perf_counter()
        try:
            res = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, check=False)
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return {
                "ok": res.returncode == 0,
                "returncode": res.returncode,
                "elapsed_ms": elapsed_ms,
                "output_tail": (res.stdout + "\n" + res.stderr).strip()[-1000:],
            }
        except Exception as exc:
            return {"ok": False, "returncode": -1, "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2), "output_tail": str(exc)}

    def analyze_improvement_opportunities(self, project_path: str = "*") -> list[dict]:
        """
        Analiza outcome_records acumulados para detectar estrategias con baja tasa de éxito
        o eficiencia subóptima y generar propuestas de experimento accionables.
        """
        engine = self.outcome_engine or OutcomeLearningEngine()
        stats = engine.get_strategy_stats(project_path=project_path)
        opportunities: list[dict] = []
        for strat, b in (stats.get("by_strategy") or {}).items():
            cnt = int(b.get("count", 0))
            if cnt < 2:
                continue
            func_rate = b["func_ok"] / cnt
            avg_eff = float(b.get("avg_efficiency", 0.0))
            if func_rate < 0.75:
                opportunities.append(
                    {
                        "target_component": "strategy",
                        "problem_detected": f"Estrategia '{strat}' tiene baja tasa de éxito funcional ({func_rate:.0%} en {cnt} ejecuciones).",
                        "evidence": f"outcome_records: count={cnt}, tech_ok={b['tech_ok']}, func_ok={b['func_ok']}, avg_efficiency={avg_eff}",
                        "hypothesis": f"Inyectar contexto estructural (Repo Map) y verificación previa reducirá fallos en '{strat}'.",
                        "proposed_change": f"Habilitar pre-check de impacto y criterios de aceptación antes de ejecutar '{strat}'.",
                        "before_metrics": {"score": round(func_rate * 100, 1), "efficiency": avg_eff},
                    }
                )
            elif avg_eff < 0.45:
                opportunities.append(
                    {
                        "target_component": "routing",
                        "problem_detected": f"Estrategia '{strat}' muestra baja eficiencia ({avg_eff}) por reintentos o consumo de tokens.",
                        "evidence": f"outcome_records: count={cnt}, avg_efficiency={avg_eff}",
                        "hypothesis": "Acotar el paquete de contexto y evitar swaps de VRAM mejorará la eficiencia.",
                        "proposed_change": "Reducir max_chars de contexto inicial y priorizar modelo residente en VRAM.",
                        "before_metrics": {"score": round(avg_eff * 100, 1), "func_rate": round(func_rate, 3)},
                    }
                )
        return opportunities

    def list_experiments(self, limit: int = 30) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM experiments ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(100, limit)),),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "target_component": r["target_component"],
                "problem_detected": r["problem_detected"],
                "evidence": r["evidence"],
                "hypothesis": r["hypothesis"],
                "proposed_change": r["proposed_change"],
                "controlled_test": r["controlled_test"],
                "before_metrics": json.loads(r["before_metrics_json"] or "{}"),
                "after_metrics": json.loads(r["after_metrics_json"] or "{}"),
                "resource_impact": json.loads(r["resource_impact_json"] or "{}"),
                "decision": r["decision"],
                "decision_reason": r["decision_reason"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
