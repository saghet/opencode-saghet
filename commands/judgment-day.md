---
description: Run Gentle AI Judgment Day dual blind review on a target
agent: saghet-orchestrator
subtask: true
---

Carga la skill `judgment-day` y ejecuta una revisión adversarial ciega de doble juez (de forma secuencial en GPU local para respetar `OLLAMA_MAX_LOADED_MODELS=1`) sobre el objetivo indicado.
