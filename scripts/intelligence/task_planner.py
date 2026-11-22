#!/usr/bin/env python3
"""
Intelligent Task Planner — OpenCode-Saghet (Fase 7 / v0.5.0).

Convierte solicitudes complejas en planes de ingeniería verificables diferenciando:
1. new_development
2. refactoring
3. migration
4. interface_transformation
5. integration
6. repair
7. research

Cada plan genera obligatoriamente:
- Objetivo funcional, requisitos, restricciones, análisis del proyecto, arquitectura propuesta,
  alternativas técnicas y recomendación, tecnologías seleccionadas, componentes reutilizables,
  tareas y dependencias (con verificación anti-conflicto de archivos), riesgos y pruebas de aceptación.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.intelligence.gemini_core import FileOwnershipCoordinator
from scripts.intelligence.semantic_engine import SemanticProjectEngine
from scripts.intelligence.visual_product import select_product_stack
from scripts.memory.hierarchical_memory import HierarchicalMemoryStore
from scripts.supervisor.gentle_ai_bridge import classify_and_route

TASK_CATEGORIES = (
    "new_development",
    "refactoring",
    "migration",
    "interface_transformation",
    "integration",
    "repair",
    "research",
)

_TRANSFORM_RE = re.compile(
    r"\b(convierte|convert|transforma|transform|cli\s+a\s+web|cli\s+to\s+web|cli\s+a\s+desktop|cli\s+to\s+desktop|"
    r"cli\s+a\s+(?:app|aplicaci[oó]n)\s*(?:web|m[oó]vil|escritorio)|web\s+a\s+desktop|desktop\s+a\s+web|monolit.*modular|a\s+saas)\b",
    re.IGNORECASE,
)
_MIGRATION_RE = re.compile(r"\b(migra|migrate|migration|actualizar\s+de\s+v\d+|portar\s+a|port\s+to)\b", re.IGNORECASE)
_REFACTOR_RE = re.compile(r"\b(refactor|refactoriza|reestructura|desacopla|decouple|limpia\s+arquitectura|extrae\s+dominio)\b", re.IGNORECASE)
_INTEGRATION_RE = re.compile(r"\b(integra|integrate|conecta|connect|api|webhook|mcp|acp|oauth|plugin|github\s+reuse|reutiliz)\b", re.IGNORECASE)
_REPAIR_RE = re.compile(r"\b(fix|corrige|repara|arregla|bug|error|fallo|crash|traceback|regresi[oó]n|debug)\b", re.IGNORECASE)
_RESEARCH_RE = re.compile(r"^\s*(investiga|analiza|audita|explica|compara|busca|evaluate|research|analyze|audit|explain|compare)\b", re.IGNORECASE)


def classify_engineering_task(objective: str) -> str:
    """Diferencia la solicitud en una de las 7 categorías formales de ingeniería."""
    text = (objective or "").strip()
    if _TRANSFORM_RE.search(text):
        return "interface_transformation"
    if _RESEARCH_RE.search(text):
        return "research"
    if _REPAIR_RE.search(text):
        return "repair"
    if _MIGRATION_RE.search(text):
        return "migration"
    if _REFACTOR_RE.search(text):
        return "refactoring"
    if _INTEGRATION_RE.search(text):
        return "integration"
    return "new_development"


class IntelligentTaskPlanner:
    """Planificador de ingeniería orientado a objetivos verificables."""

    def __init__(
        self,
        semantic_engine: SemanticProjectEngine | None = None,
        memory_store: HierarchicalMemoryStore | None = None,
    ) -> None:
        self.memory = memory_store
        self.semantic = semantic_engine or SemanticProjectEngine(memory_store=memory_store)
        self.ownership = FileOwnershipCoordinator()

    def build_plan(
        self,
        objective: str,
        project_path: Path | str | None = None,
        target_platform: str | None = None,
        reuse_reports: list[dict] | None = None,
    ) -> dict:
        text = (objective or "").strip()
        category = classify_engineering_task(text)
        routing = classify_and_route(
            objective=text,
            project_path=str(project_path) if project_path else "*",
            memory_store=self.memory,
        )
        intent = routing.get("intent_analysis") or {}

        proj_analysis: dict = {"analyzed": False}
        primary_lang = "Python"
        reusable_components: list[dict] = []
        if project_path and Path(project_path).is_dir():
            sem = self.semantic.analyze_codebase(project_path)
            if sem.get("ok"):
                ci = sem["codebase_intelligence"]
                primary_lang = ci["primary_language"]
                reusable_components = ci.get("reusable_components", [])[:8]
                proj_analysis = {
                    "analyzed": True,
                    "primary_language": primary_lang,
                    "frameworks": ci["frameworks"],
                    "total_files": sem["index_stats"]["total_files"],
                    "business_logic_files": ci["business_logic_files"][:10],
                    "circular_dependencies_count": len(ci["circular_dependencies"]),
                }

        # Detectar plataforma destino si se trata de transformación o desarrollo UI
        detected_platform = target_platform
        low = text.lower()
        if not detected_platform:
            if any(k in low for k in ("desktop", "escritorio", "tauri", "electron", "pyqt", "qt")):
                detected_platform = "desktop"
            elif any(k in low for k in ("mobile", "móvil", "movil", "flutter", "react native", "android", "ios")):
                detected_platform = "mobile"
            elif any(k in low for k in ("web", "dashboard", "frontend", "saas", "navegador", "browser")):
                detected_platform = "web"

        selected_tech = (
            select_product_stack(detected_platform, primary_lang, project_size="medium")
            if detected_platform
            else {
                "target_platform": "backend_or_library",
                "selected": {"runtime": primary_lang, "rationale": "Alineado con el stack existente del proyecto."},
                "alternatives_evaluated": [],
            }
        )

        # Requisitos funcionales y restricciones
        requirements = [
            f"Cumplir objetivo funcional ({category}): {text[:220]}",
            "Preservar compatibilidad con funcionalidades existentes sin regresiones.",
            "Entregar evidencia verificable de compilación, ejecución y pruebas automatizadas.",
        ]
        if category == "interface_transformation":
            requirements.append("Separar lógica de dominio de la interfaz original (cero wrappers que impriman comandos CLI).")
            requirements.append("Validar equivalencia funcional 1:1 mediante Matriz de Equivalencia ejecutable.")

        constraints = list(intent.get("explicit_constraints") or []) + list(intent.get("contextual_constraints") or [])
        constraints.append("Respetar políticas de seguridad, licencias SPDX y aislamiento Git worktree en cambios de riesgo.")

        # Alternativas arquitectónicas y recomendación técnica
        alternatives = [
            {
                "option": "A: Arquitectura por capas proporcional (Domain / Application / API / Presentation / Adapter CLI)",
                "recommended": True,
                "rationale": "Separa reglas de negocio de la UI, conserva la CLI original y facilita pruebas de equivalencia.",
            },
            {
                "option": "B: Refactor mínimo in-place con adaptador directo",
                "recommended": False,
                "rationale": "Menor coste inicial en scripts pequeños, pero menor reutilización para futuras plataformas.",
            },
        ]

        # Tareas con dependencias y ownership explícito para evitar conflictos
        tasks = self._generate_tasks_for_category(category, detected_platform)
        file_conflicts = self.ownership.detect_plan_conflicts(tasks)

        risks = [
            "Regresión en consumidores existentes si cambian contratos públicos.",
            "Ambigüedad de requisitos de interfaz o datos si no se acuerdan criterios de aceptación.",
        ]
        if category == "interface_transformation":
            risks.append("Pérdida de paridad funcional o creación de controles UI no conectados a lógica real.")
        if reuse_reports:
            for rep in reuse_reports:
                risks.extend(rep.get("risks") or [])

        acceptance_tests = [
            "Ejecución limpia de pruebas unitarias y de regresión existentes (exit code 0).",
            "Revisión independiente (`code-reviewer` + `architecture-validation-specialist`) sin hallazgos críticos.",
        ]
        if category == "interface_transformation":
            acceptance_tests.append("Matriz de Equivalencia Funcional 100% PASS entre CLI original y nueva interfaz.")
            acceptance_tests.append("Validación Anti-UI Falsa (`validate_ui_product_integrity`) con 0 violaciones.")

        # No empezar a programar sin comprender qué resultado espera el usuario si la ambigüedad es determinante
        requires_clarification = bool(intent.get("requires_clarification", False))
        clarification_questions: list[str] = []
        if intent.get("clarification_question"):
            clarification_questions.append(intent["clarification_question"])
        if category == "interface_transformation" and not detected_platform:
            requires_clarification = True
            clarification_questions.append("¿Qué plataforma destino prefieres: Web, Escritorio (PyQt6/Tauri/Electron) o Móvil?")

        return {
            "ok": True,
            "task_category": category,
            "functional_objective": text,
            "requirements": requirements,
            "constraints": constraints[:10],
            "project_analysis": proj_analysis,
            "proposed_architecture": {
                "recommended_option": alternatives[0]["option"],
                "rationale": alternatives[0]["rationale"],
                "alternatives": alternatives,
            },
            "selected_technologies": selected_tech,
            "reusable_components": reusable_components,
            "external_reuse_reports": list(reuse_reports or []),
            "tasks_and_dependencies": tasks,
            "file_ownership_conflicts": file_conflicts,
            "risks": risks[:10],
            "acceptance_tests": acceptance_tests,
            "requires_clarification": requires_clarification,
            "clarification_questions": clarification_questions,
            "gentle_ai_routing": {
                "complexity": routing["complexity"],
                "risk": routing["risk"],
                "primary_specialist": routing["primary_specialist"],
                "worktree_required": routing["worktree_required"],
            },
        }

    @staticmethod
    def _generate_tasks_for_category(category: str, platform: str | None) -> list[dict]:
        if category == "interface_transformation":
            return [
                {"id": "t1_analyze", "title": "Analizar dominio y comandos originales", "specialist": "repository-intelligence-specialist", "dependencies": [], "write_files": []},
                {"id": "t2_domain", "title": "Extraer capa Domain y Application preservando CLI", "specialist": "domain-engineering-specialist", "dependencies": ["t1_analyze"], "write_files": ["domain/core.py", "application/use_cases.py", "adapters/cli.py"]},
                {"id": "t3_api", "title": "Construir capa API y contratos reales", "specialist": "api-integration-specialist", "dependencies": ["t2_domain"], "write_files": ["api/server.py"]},
                {"id": "t4_ui", "title": f"Construir interfaz gráfica real ({platform or 'web'})", "specialist": "frontend-product-engineer", "dependencies": ["t3_api"], "write_files": ["presentation/index.html", "presentation/app.js", "presentation/styles.css"]},
                {"id": "t5_validate", "title": "Ejecutar pruebas de equivalencia y revisión arquitectónica", "specialist": "architecture-validation-specialist", "dependencies": ["t4_ui"], "write_files": []},
            ]
        if category == "research":
            return [
                {"id": "t1_research", "title": "Investigar repositorio, dependencias y alternativas", "specialist": "repository-intelligence-specialist", "dependencies": [], "write_files": []},
                {"id": "t2_license", "title": "Auditar licencias SPDX y compatibilidad", "specialist": "license-compliance-specialist", "dependencies": ["t1_research"], "write_files": []},
            ]
        if category == "repair":
            return [
                {"id": "t1_context", "title": "Recuperar contexto de impacto y reproducir fallo", "specialist": "qa-engineer", "dependencies": [], "write_files": []},
                {"id": "t2_fix", "title": "Aplicar corrección atómica sin regresiones", "specialist": "senior-developer", "dependencies": ["t1_context"], "write_files": ["target_module"]},
                {"id": "t3_verify", "title": "Validar con pruebas reales y revisión independiente", "specialist": "code-reviewer", "dependencies": ["t2_fix"], "write_files": []},
            ]
        return [
            {"id": "t1_design", "title": "Diseñar arquitectura y contratos", "specialist": "semantic-architecture-specialist", "dependencies": [], "write_files": []},
            {"id": "t2_reuse", "title": "Evaluar reutilización de componentes existentes/GitHub", "specialist": "code-reuse-specialist", "dependencies": ["t1_design"], "write_files": []},
            {"id": "t3_impl", "title": "Implementar solución modular", "specialist": "senior-developer", "dependencies": ["t2_reuse"], "write_files": ["src/implementation"]},
            {"id": "t4_qa", "title": "Ejecutar pruebas reales y validación arquitectónica", "specialist": "qa-engineer", "dependencies": ["t3_impl"], "write_files": []},
        ]
