---
description: Generate a verified Intelligent Engineering Plan (Semantic Graph + Reuse + Architecture + Acceptance Tests)
agent: saghet-orchestrator
---

Ejecuta el Planificador Inteligente antes de diseñar o transformar un proyecto:
`python3 -c "import json; from scripts.intelligence.task_planner import IntelligentTaskPlanner; print(json.dumps(IntelligentTaskPlanner().build_plan('$ARGUMENTS', project_path='.'), indent=2, ensure_ascii=False))"`

Reglas obligatorias:
1. Si `requires_clarification=true`, formula únicamente las preguntas determinantes antes de programar.
2. En transformaciones CLI→Web/Desktop/Mobile, extrae el dominio real (`domain-engineering-specialist`), construye UI conectada (`frontend-product-engineer`) y valida equivalencia funcional 1:1 (`architecture-validation-specialist`).
3. En reutilización externa, ejecuta inspección estática y auditoría SPDX (`license-compliance-specialist`) sin ejecutar scripts del repo externo.
