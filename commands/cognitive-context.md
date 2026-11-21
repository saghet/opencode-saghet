---
description: Prepare live cognitive context (User Intelligence, Semantic Memory, Project Continuity & Adaptive Plan)
agent: saghet-orchestrator
---

Ejecuta el puente cognitivo en 1 sola llamada antes de planificar o editar:
`python3 -m scripts.supervisor.cognitive_bridge --prepare "$ARGUMENTS" --project .`

Usa `compact_context_prompt`, `requires_clarification` y `routing.reasoning_plan` para:
1. Responder con una única pregunta de alto valor si `requires_clarification=true`.
2. Respetar preferencias, restricciones y decisiones previas sin repetir errores.
3. Ajustar la estrategia y presupuesto sin lanzar DAGs innecesarios en tareas simples.
