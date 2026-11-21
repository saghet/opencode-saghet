#!/usr/bin/env python3
"""
Puente Vivo Cognitivo — OpenCode-Saghet Cognitive V2 (Fase A).

Conecta en un único punto de entrada liviano (`< 50 ms` en memoria/índice local):
- `UserIntelligenceEngine` (captura de preferencias/correcciones + privacidad)
- `IntentUnderstandingEngine` + `build_adaptive_reasoning_plan` (`gentle_ai_bridge`)
- `HierarchicalMemoryStore` (paquete contextual acotado + consolidación)
- `ProjectIntelligenceEngine` (indexación incremental + continuidad entre sesiones)
- `OutcomeLearningEngine` (registro de resultados verificados en 4 dimensiones)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from scripts.memory.hierarchical_memory import HierarchicalMemoryStore
from scripts.memory.outcome_learning import OutcomeLearningEngine
from scripts.memory.project_intelligence import ProjectIntelligenceEngine
from scripts.memory.user_intelligence import UserIntelligenceEngine
from scripts.supervisor.gentle_ai_bridge import classify_and_route

_CONTINUITY_TRIGGER_RE = re.compile(
    r"\b(continuemos|contin[uú]a|retomemos|donde\s+quedamos|continue|resume|where\s+we\s+left\s+off)\b",
    re.IGNORECASE,
)


class CognitiveBridge:
    """Orquesta el ciclo cognitivo completo (pre-turno y post-turno) sobre almacenamiento local."""

    def __init__(
        self,
        memory_db_path: Path | None = None,
        project_db_path: Path | None = None,
    ) -> None:
        self.memory = HierarchicalMemoryStore(db_path=memory_db_path)
        self.user_engine = UserIntelligenceEngine(memory_store=self.memory)
        self.project_engine = ProjectIntelligenceEngine(db_path=project_db_path, memory_store=self.memory)
        self.outcome_engine = OutcomeLearningEngine(memory_store=self.memory, user_engine=self.user_engine)

    def prepare_turn_context(
        self,
        objective: str,
        project_path: str = ".",
        session_id: str = "",
        context_files: list[str] | None = None,
        max_chars: int = 2400,
    ) -> dict:
        """
        Pre-turno: captura señales del usuario, indexa incrementalmente el proyecto,
        interpreta intención/estrategia adaptativa y construye contexto compacto.
        """
        resolved_proj = str(Path(project_path).resolve()) if project_path and project_path != "*" else "*"

        capture_res = self.user_engine.detect_and_capture_from_message(
            message=objective,
            project_path=resolved_proj,
            session_id=session_id,
        )

        index_stats = None
        continuity = None
        project_context = None
        if resolved_proj != "*" and Path(resolved_proj).is_dir():
            index_stats = self.project_engine.index_project(resolved_proj)
            project_context = self.project_engine.select_relevant_context(
                objective=objective,
                project_path=resolved_proj,
                max_chars=max(600, max_chars // 2),
            )
            if _CONTINUITY_TRIGGER_RE.search(objective or ""):
                continuity = self.project_engine.reconstruct_continuity_context(resolved_proj)

        routing = classify_and_route(
            objective=objective,
            context_files=context_files,
            project_path=resolved_proj,
            memory_store=self.memory,
            user_engine=self.user_engine,
        )

        memory_pack = self.memory.build_contextual_memory_pack(
            objective=objective,
            project_path=resolved_proj,
            session_id=session_id,
            max_chars=max_chars,
        )

        # Ensamblar bloque compacto para inyectar en el prompt del agente
        sections: list[str] = []
        intent_info = routing.get("intent_analysis") or {}
        r_plan = routing.get("reasoning_plan") or {}
        sections.append(
            f"[COGNITIVE_PLAN] strategy={r_plan.get('strategy')} | specialist={routing.get('primary_specialist')} "
            f"| model={routing.get('selected_model')} | token_budget={r_plan.get('token_budget')} "
            f"| use_dag={r_plan.get('use_dag')}"
        )
        if intent_info.get("explicit_constraints"):
            sections.append("[EXPLICIT_CONSTRAINTS] " + "; ".join(intent_info["explicit_constraints"]))
        if memory_pack.get("context_text"):
            sections.append("[MEMORY_CONTEXT]\n" + memory_pack["context_text"])
        if project_context and project_context.get("context_text"):
            sections.append("[PROJECT_INTELLIGENCE]\n" + project_context["context_text"])
        if continuity and continuity.get("has_saved_state"):
            sections.append(
                "[PROJECT_CONTINUITY] "
                f"completed={continuity.get('completed_features', [])[:3]} | "
                f"pending={continuity.get('pending_features', [])[:3]} | "
                f"next={continuity.get('next_recommended_step', '')}"
            )

        compact_prompt = "\n".join(sections)[:max_chars]

        return {
            "ok": True,
            "project_path": resolved_proj,
            "captured_user_signals": capture_res,
            "index_stats": index_stats,
            "project_context": project_context,
            "continuity": continuity,
            "routing": routing,
            "memory_pack": memory_pack,
            "requires_clarification": bool(intent_info.get("requires_clarification", False)),
            "clarification_question": intent_info.get("clarification_question"),
            "compact_context_prompt": compact_prompt,
        }

    def finalize_turn_outcome(
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
        project_path: str = ".",
        elapsed_s: float = 0.0,
        tokens_used: int = 0,
        token_budget: int = 2048,
        completed_feature: str | None = None,
        next_recommended_step: str | None = None,
    ) -> dict:
        """
        Post-turno: registra resultado en 4 dimensiones, actualiza continuidad del proyecto
        si hubo avance verificado y consolida experiencias repetidas.
        """
        resolved_proj = str(Path(project_path).resolve()) if project_path and project_path != "*" else "*"
        outcome = self.outcome_engine.record_outcome(
            objective=objective,
            strategy=strategy,
            model=model,
            specialists=specialists,
            tools_used=tools_used,
            attempts=attempts,
            errors=errors,
            technical_success=technical_success,
            functional_success=functional_success,
            project_path=resolved_proj,
            elapsed_s=elapsed_s,
            tokens_used=tokens_used,
            token_budget=token_budget,
        )

        consolidation = None
        if technical_success and functional_success and resolved_proj != "*" and Path(resolved_proj).is_dir():
            if completed_feature or next_recommended_step:
                prev = self.project_engine.reconstruct_continuity_context(resolved_proj)
                completed_list = list(prev.get("completed_features") or [])
                if completed_feature and completed_feature not in completed_list:
                    completed_list.append(completed_feature)
                self.project_engine.save_project_state(
                    project_path=resolved_proj,
                    completed_features=completed_list,
                    next_recommended_step=next_recommended_step,
                )
            consolidation = self.memory.consolidate_experiences(project_path=resolved_proj, min_occurrences=2)

        return {
            "ok": True,
            "outcome": outcome,
            "consolidation": consolidation,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Saghet Cognitive Bridge CLI")
    parser.add_argument("--prepare", default="", help="Prepara contexto cognitivo para un objetivo")
    parser.add_argument("--project", default=".", help="Ruta del proyecto")
    parser.add_argument("--session", default="", help="ID de sesión")
    args = parser.parse_args()

    bridge = CognitiveBridge()
    if args.prepare:
        res = bridge.prepare_turn_context(args.prepare, project_path=args.project, session_id=args.session)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
