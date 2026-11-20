# ADR-003: Adaptador Desacoplado DeepSeek Harness vía ACP (Sin Cordis en el Núcleo)

- **Estado:** Aceptado y Verificado en Producción
- **Fecha:** 2026-11-20
- **Contexto:** DeepSeek Harness (`deepseek-ai/deepseek-harness`) ofrece coordinación de workflows, Task Board, delegación vía ACP (`dsh-subagent-acp`) y trazas de ejecución, pero su núcleo está basado en el micro-kernel de plugins **Cordis**. Incorporar Cordis dentro de OpenCode v2.3.2 duplicaría el sistema nativo `@opencode/plugin` y rompería la compatibilidad con actualizaciones de `pacman` en Garuda/Arch Linux.
- **Decisión:**
  1. **No incorporar Cordis en el núcleo (`cordis_in_core: false`)** ni duplicar la gestión de agentes, sesiones o memoria (`duplicate_state_stores: false`).
  2. Conectar las capacidades de coordinación de workflows complejos mediante un **Adaptador ACP JSON-RPC 2.0 sobre stdio** ([scripts/harness/acp_adapter.py](file:///home/saghet/Documents/OpenCode-Saghet/scripts/harness/acp_adapter.py) y [scripts/harness/workflow_engine.py](file:///home/saghet/Documents/OpenCode-Saghet/scripts/harness/workflow_engine.py)) que utiliza `opencode acp` como motor de ejecución y a Gentle AI como autoridad de selección de modelo y especialista.
  3. Serializar mediante lock todos los nodos del DAG con `requires_gpu=True` para respetar `OLLAMA_MAX_LOADED_MODELS=1`, permitiendo paralelismo en nodos no-GPU.
  4. Hacer el adaptador completamente conmutable (`config/harness.json` -> `"enabled": true | false` o `SAGHET_HARNESS_ENABLED=0`), con fallback transparente a OpenCode nativo.
- **Consecuencias:** Se obtienen workflows DAG, Task Board, sesiones persistentes, Execution Traces append-only y recuperación ante fallos sin acoplamiento ni deuda técnica frente al upstream de OpenCode.
