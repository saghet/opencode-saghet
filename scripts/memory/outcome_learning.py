#!/usr/bin/env python3
"""
Outcome Learning & Skill Evolution Engine — OpenCode-Saghet Cognitive V2 (Fase 5).

Diferencia éxito técnico, éxito funcional, satisfacción del usuario y eficiencia de ejecución.
Aprende de resultados verificados y feedback real, y gestiona la evolución controlada
de Skills reutilizables con detección de duplicados, validación aislada e historial/rollback.
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path

from scripts.memory.hierarchical_memory import (
    HierarchicalMemoryStore,
    contains_sensitive_secret,
    jaccard_similarity,
    tokenize_meaningful,
)
from scripts.memory.user_intelligence import UserIntelligenceEngine

REPO_DIR = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_DIR / "skills"


class OutcomeLearningEngine:
    """
    Motor de aprendizaje basado en resultados verificados y evolución controlada de Skills.
    Reutiliza el almacén SQLite de `HierarchicalMemoryStore` sin crear bases redundantes.
    """

    def __init__(
        self,
        memory_store: HierarchicalMemoryStore | None = None,
        user_engine: UserIntelligenceEngine | None = None,
        skills_dir: Path | None = None,
    ) -> None:
        self.memory = memory_store or HierarchicalMemoryStore()
        self.user_engine = user_engine or UserIntelligenceEngine(self.memory)
        self.skills_dir = Path(skills_dir or SKILLS_DIR)
        self._init_table()

    def _connect(self):
        conn = sqlite3.connect(str(self.memory.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return contextlib.closing(conn)

    def _init_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outcome_records (
                    outcome_id TEXT PRIMARY KEY,
                    project_path TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    model TEXT NOT NULL,
                    specialists_json TEXT NOT NULL,
                    tools_json TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    errors_json TEXT NOT NULL,
                    technical_success INTEGER NOT NULL,
                    functional_success INTEGER NOT NULL,
                    user_accepted INTEGER DEFAULT NULL,
                    rejection_reason TEXT DEFAULT '',
                    subsequent_changes TEXT DEFAULT '',
                    efficiency_score REAL NOT NULL,
                    elapsed_s REAL NOT NULL DEFAULT 0.0,
                    tokens_used INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_outcome_proj ON outcome_records(project_path)")
            conn.commit()

    @staticmethod
    def compute_efficiency_score(attempts: int, elapsed_s: float, tokens_used: int, token_budget: int = 2048) -> float:
        attempt_penalty = max(0, attempts - 1) * 0.18
        budget_ratio = (tokens_used / max(1, token_budget)) if tokens_used > 0 else 0.5
        budget_penalty = max(0.0, (budget_ratio - 1.0) * 0.25)
        time_penalty = max(0.0, (elapsed_s - 30.0) / 120.0) * 0.15
        return round(max(0.0, min(1.0, 1.0 - attempt_penalty - budget_penalty - time_penalty)), 3)

    def record_outcome(
        self,
        objective: str,
        strategy: str,
        model: str,
        specialists: list[str],
        tools_used: list[str],
        attempts: int,
        errors: list[str],
        technical_success: bool,
        functional_success: bool,
        project_path: str = "*",
        elapsed_s: float = 0.0,
        tokens_used: int = 0,
        token_budget: int = 2048,
        user_accepted: bool | None = None,
        rejection_reason: str = "",
    ) -> dict:
        """
        Registra un resultado de ejecución evaluando sus 4 dimensiones por separado:
        éxito técnico, éxito funcional, satisfacción del usuario y eficiencia.
        """
        norm_proj = str(Path(project_path).resolve()) if project_path and project_path != "*" else "*"
        outcome_id = f"out_{uuid.uuid4().hex[:12]}"
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        eff = self.compute_efficiency_score(attempts, elapsed_s, tokens_used, token_budget)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO outcome_records (
                    outcome_id, project_path, objective, strategy, model,
                    specialists_json, tools_json, attempts, errors_json,
                    technical_success, functional_success, user_accepted,
                    rejection_reason, subsequent_changes, efficiency_score,
                    elapsed_s, tokens_used, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?)
                """,
                (
                    outcome_id,
                    norm_proj,
                    (objective or "")[:400],
                    strategy,
                    model,
                    json.dumps(specialists, ensure_ascii=False),
                    json.dumps(tools_used, ensure_ascii=False),
                    max(1, int(attempts)),
                    json.dumps(errors, ensure_ascii=False),
                    1 if technical_success else 0,
                    1 if functional_success else 0,
                    (1 if user_accepted else 0) if user_accepted is not None else None,
                    rejection_reason[:300],
                    eff,
                    float(elapsed_s),
                    int(tokens_used),
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()

        # Solo almacenar como solución verificada si tanto lo técnico como lo funcional pasaron
        if technical_success and functional_success:
            self.memory.store_memory(
                tier="experience",
                category="verified_execution",
                title=f"Ejecución verificada ({strategy}): {(objective or '')[:90]}",
                content=f"Estrategia: {strategy} | Modelo: {model} | Intentos: {attempts} | Eficiencia: {eff}",
                provenance=f"outcome:{outcome_id}",
                project_path=norm_proj,
                context={"tags": ["outcome", strategy, *specialists], "outcome_id": outcome_id},
                confidence=0.90 if attempts == 1 else 0.84,
                importance=0.80,
                evidence={"technical_success": True, "functional_success": True, "efficiency": eff},
            )

        return {
            "ok": True,
            "outcome_id": outcome_id,
            "dimensions": {
                "technical_success": bool(technical_success),
                "functional_success": bool(functional_success),
                "user_satisfaction": user_accepted,
                "execution_efficiency": eff,
            },
        }

    def record_user_feedback(
        self,
        outcome_id: str,
        accepted: bool,
        reason: str = "",
        subsequent_changes: str = "",
    ) -> dict:
        """
        Actualiza el ciclo de retroalimentación del usuario sobre un resultado registrado.
        """
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM outcome_records WHERE outcome_id = ?", (outcome_id,)).fetchone()
            if row is None:
                return {"ok": False, "error": f"Outcome no encontrado: {outcome_id}"}
            conn.execute(
                """
                UPDATE outcome_records
                SET user_accepted = ?, rejection_reason = ?, subsequent_changes = ?, updated_at = ?
                WHERE outcome_id = ?
                """,
                (1 if accepted else 0, (reason or "")[:300], (subsequent_changes or "")[:300], now_iso, outcome_id),
            )
            conn.commit()

        self.user_engine.record_outcome_signal(
            solution_summary=f"{row['objective']} (estrategia={row['strategy']}, modelo={row['model']})",
            accepted=accepted,
            reason=reason or subsequent_changes,
            project_path=row["project_path"],
            tags=["outcome_feedback", row["strategy"]],
        )
        return {
            "ok": True,
            "outcome_id": outcome_id,
            "user_accepted": accepted,
            "technical_success": bool(row["technical_success"]),
            "functional_success": bool(row["functional_success"]),
        }

    def get_strategy_stats(self, project_path: str = "*") -> dict:
        norm_proj = str(Path(project_path).resolve()) if project_path and project_path != "*" else "*"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM outcome_records WHERE (? = '*' OR project_path IN ('*', ?)) ORDER BY created_at DESC LIMIT 100",
                (norm_proj, norm_proj),
            ).fetchall()

        by_strategy: dict[str, dict] = {}
        for r in rows:
            st = r["strategy"]
            bucket = by_strategy.setdefault(
                st,
                {"count": 0, "tech_ok": 0, "func_ok": 0, "user_ok": 0, "user_rated": 0, "avg_efficiency": 0.0},
            )
            bucket["count"] += 1
            bucket["tech_ok"] += int(r["technical_success"])
            bucket["func_ok"] += int(r["functional_success"])
            if r["user_accepted"] is not None:
                bucket["user_rated"] += 1
                bucket["user_ok"] += int(r["user_accepted"])
            bucket["avg_efficiency"] += float(r["efficiency_score"])

        for b in by_strategy.values():
            b["avg_efficiency"] = round(b["avg_efficiency"] / max(1, b["count"]), 3)
        return {"total_outcomes": len(rows), "by_strategy": by_strategy}

    def find_equivalent_skill(self, candidate_name: str, candidate_description: str) -> str | None:
        """Verifica si ya existe una Skill equivalente en `skills/` para evitar duplicación."""
        if not self.skills_dir.is_dir():
            return None
        cand_tokens = tokenize_meaningful(f"{candidate_name} {candidate_description}")
        for skill_md in self.skills_dir.glob("*/SKILL.md"):
            existing_name = skill_md.parent.name
            if existing_name.lower() == candidate_name.lower():
                return str(skill_md)
            txt = skill_md.read_text(encoding="utf-8", errors="replace")[:800]
            if jaccard_similarity(cand_tokens, tokenize_meaningful(f"{existing_name} {txt}")) >= 0.65:
                return str(skill_md)
        return None

    def propose_skill_from_patterns(
        self,
        skill_name: str,
        description: str,
        steps: list[str],
        project_path: str = "*",
        min_verified_outcomes: int = 2,
    ) -> dict:
        """
        Propone una Skill solo si existe respaldo de >= `min_verified_outcomes` ejecuciones
        técnica y funcionalmente exitosas (sin rechazo del usuario) y no existe una equivalente.
        """
        clean_name = re.sub(r"[^a-z0-9-]", "-", (skill_name or "").lower()).strip("-")
        if not clean_name or not description.strip() or not steps:
            return {"ok": False, "error": "skill_name, description y steps son obligatorios"}
        if contains_sensitive_secret(description) or any(contains_sensitive_secret(s) for s in steps):
            return {"ok": False, "error": "Bloqueado por privacidad: la Skill contiene secretos"}

        dup = self.find_equivalent_skill(clean_name, description)
        if dup:
            return {"ok": False, "duplicate_of": dup, "error": f"Ya existe una Skill equivalente: {dup}"}

        norm_proj = str(Path(project_path).resolve()) if project_path and project_path != "*" else "*"
        with self._connect() as conn:
            verified_cnt = conn.execute(
                """
                SELECT COUNT(*) FROM outcome_records
                WHERE technical_success = 1 AND functional_success = 1
                  AND (user_accepted IS NULL OR user_accepted = 1)
                  AND (? = '*' OR project_path IN ('*', ?))
                """,
                (norm_proj, norm_proj),
            ).fetchone()[0]

        if verified_cnt < min_verified_outcomes:
            return {
                "ok": False,
                "error": f"Evidencia insuficiente ({verified_cnt}/{min_verified_outcomes} ejecuciones verificadas).",
            }

        body_lines = [
            "---",
            f"name: {clean_name}",
            f"description: {description.strip()}",
            "---",
            "",
            f"# {clean_name}",
            "",
            *[f"{idx}. {step.strip()}" for idx, step in enumerate(steps, 1)],
            "",
        ]
        markdown = "\n".join(body_lines)
        valid, reason = self.validate_skill_markdown(markdown)
        if not valid:
            return {"ok": False, "error": reason}

        return {
            "ok": True,
            "skill_name": clean_name,
            "verified_evidence_count": verified_cnt,
            "markdown": markdown,
        }

    @staticmethod
    def validate_skill_markdown(markdown: str) -> tuple[bool, str]:
        """Valida en aislamiento el formato frontmatter, ausencia de secretos y estructura mínima."""
        if contains_sensitive_secret(markdown):
            return False, "La Skill contiene secretos o credenciales"
        if not markdown.startswith("---\n") or "\nname:" not in markdown or "\ndescription:" not in markdown:
            return False, "Falta frontmatter YAML válido (name/description)"
        if len(markdown.splitlines()) < 6:
            return False, "La Skill carece de pasos accionables"
        return True, "OK"

    def install_and_rollback_skill(
        self,
        skill_name: str,
        markdown: str,
        approve: bool = True,
    ) -> dict:
        """Instala una Skill validada en `skills/<name>/SKILL.md` o la revierte (rollback)."""
        clean_name = re.sub(r"[^a-z0-9-]", "-", (skill_name or "").lower()).strip("-")
        target_dir = self.skills_dir / clean_name
        target_file = target_dir / "SKILL.md"

        if not approve:
            if target_file.is_file():
                target_file.unlink()
            if target_dir.is_dir() and not any(target_dir.iterdir()):
                target_dir.rmdir()
            return {"ok": True, "rolled_back": True, "skill_name": clean_name}

        valid, reason = self.validate_skill_markdown(markdown)
        if not valid:
            return {"ok": False, "error": reason}

        target_dir.mkdir(parents=True, exist_ok=True)
        target_file.write_text(markdown, encoding="utf-8")
        return {"ok": True, "installed": True, "path": str(target_file)}
