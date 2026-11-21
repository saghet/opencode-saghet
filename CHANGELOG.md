# Changelog — OpenCode-Saghet

## [v0.3.0-cognitive-v2] — 2026-11-21

### Saghet Cognitive Intelligence V2
- **User Intelligence Engine ([scripts/memory/user_intelligence.py](scripts/memory/user_intelligence.py)):** Modelo contextual del usuario con preferencias explícitas vs. inferidas, temporales vs. permanentes, resolución de conflictos (`explicit > inferred`, estado `superseded`), aprendizaje de correcciones multilingüe (ES/EN) y privacidad estricta (sin secretos ni preferencias sensibles sin autorización; inspección, corrección y borrado).
- **Intent Understanding & Adaptive Reasoning ([scripts/supervisor/gentle_ai_bridge.py](scripts/supervisor/gentle_ai_bridge.py)):** Interpretación estructurada (`TypedIntent`), soporte ES/EN con abreviaturas/correferencias, refinamiento LLM opcional (`use_llm`), preguntas únicas de alto valor y planificación proporcional (`use_dag`, `token_budget`, `replan_after_failure`).
- **Semantic Memory Engine ([scripts/memory/hierarchical_memory.py](scripts/memory/hierarchical_memory.py)):** Índice SQLite FTS5 (`memories_fts` BM25) + expansión semántica bilingüe + embeddings locales (`embedding_json`), decaimiento por recencia, relaciones tipadas (`link_memories`), `build_contextual_memory_pack()` y `consolidate_experiences()`.
- **Project Intelligence & Continuity ([scripts/memory/project_intelligence.py](scripts/memory/project_intelligence.py)):** Indexación incremental en SQLite (AST Python, símbolos, imports, dependencias, pruebas y Git) con análisis de impacto y reconstrucción real de continuidad entre sesiones.
- **Outcome Learning & Engineering Intelligence ([scripts/memory/outcome_learning.py](scripts/memory/outcome_learning.py), [scripts/supervisor/quality_supervisor.py](scripts/supervisor/quality_supervisor.py), [scripts/harness/acp_adapter.py](scripts/harness/acp_adapter.py)):** Registro en 4 dimensiones (técnica, funcional, satisfacción, eficiencia), evolución controlada de Skills con rollback, taxonomía de 10 clases de error, `Independent Review 2.0`, `execute_acp_stdio()` y guardia contra *prompt injection*.
- **Puente Vivo, Router 2.0 y Benchmarks ([scripts/supervisor/cognitive_bridge.py](scripts/supervisor/cognitive_bridge.py), [scripts/eval/model_lab.py](scripts/eval/model_lab.py), [tests/benchmarks/run_cognitive_benchmarks.py](tests/benchmarks/run_cognitive_benchmarks.py)):** `/cognitive-context`, métricas no evaluadas marcadas como `unknown`, histéresis anti-swap VRAM (`<= 5.0` pts), suite cognitiva (`12/12`, `100.0 %`), aceptación en vivo (`15/15`) y benchmark real con `qwen3.5:9b` (`9/10`, `90.0 %`, `6758 MiB` VRAM).

## [v0.2.1-stability-hotfix] — 2026-11-21

### Estabilidad, Contexto `24k` y Diagnóstico en Vivo
- **Contexto físico `24576` (`24k`) en Ollama ([scripts/configure-ollama-ctx.sh](scripts/configure-ollama-ctx.sh)):**
  - Configura de forma idempotente `PARAMETER num_ctx 24576` en `qwen3.5:9b`, `qwen3.5:4b` y `abliterant/qwen3.5-rana:9b` sin duplicar blobs en disco.
  - Ajusta el colchón lógico en [config/opencode.json.tpl](config/opencode.json.tpl) a `context: 22528` / `output: 2560` y [config/dcp.jsonc](config/dcp.jsonc) a `minContextLimit: 8500` / `maxContextLimit: 18000` (`protectUserMessages: true`, `purgeErrors.turns: 2`), eliminando tormentas de compactación y truncamientos `output-limit`.
- **Protección Anti-Bucles `deepseek-r1`:**
  - Etiquetados `deepseek-r1:8b` y `huihui_ai/deepseek-r1-abliterated:8b-0528-qwen3` como `(Solo Chat / Sin Tools)` en el selector de la UI, con `num_predict=3072` y `repeat_penalty=1.15` en Ollama para evitar bucles infinitos de `<think>`.
- **Motor de Diagnóstico de Sesiones en Vivo ([scripts/supervisor/session_diagnostics.py](scripts/supervisor/session_diagnostics.py)):**
  - Inspección SQLite solo-lectura (`mode=ro`) de `opencode.db`, sockets `:11434`, `opencode-mem.log` y `num_ctx` de Ollama, expuesta en `GET /api/supervisor/session-health` y en el **Agent Command Center** del Control Center.
  - Detección automática de `stalled_sessions`, `compaction_storms`, `amnesia_events`, `skill_agent_confusion`, `webfetch_invalid_json_format`, `subagent_recursion_error`, `missing_file_or_dir`, `edit_oldstring_mismatch`, `service_restart_interruption`, `output-limit`, `reasoning_starvation_no_tools` y `silent_premature_stop`.
- **Endurecimiento de Reglas y Permisos ([config/opencode.json.tpl](config/opencode.json.tpl), [config/AGENTS.md](config/AGENTS.md), [install.sh](install.sh)):**
  - `autoCaptureEnabled: false` en `config/opencode-mem.jsonc` para eliminar bloqueos de `45s x 3` por `StructuredOutput` y colas zombi en `:11434`.
  - `"subagent": false` en los 16 subagentes y `plan`; secuencialidad estricta de 1 subagente local a la vez; `"ollama run *": "deny"` y `"sudo *": "ask"`.
  - Protocolos `OBJETIVO INMUTABLE`, `READ-BEFORE-EDIT & EDICIÓN ATÓMICA` y `CONTINUIDAD TRAS HERRAMIENTAS`.
  - Bandera `--restart-service` en `install.sh` y verificación extendida en `doctor.sh` + `test_o_hotfix_phase3_session_diagnostics_engine` (`15/15` tests en `tests/run_acceptance.py`).

## [v0.2.0-matrix-nextgen] — 2026-11-20
- Lanzamiento completo de las 8 fases del **Next-Gen Engineering Upgrade**: Blindaje P0, Supervisor de Calidad + Gentle AI 4.5.0 + 17 especialistas, Model Evaluation Lab (12 métricas), Memoria Jerárquica (4 niveles), DeepSeek Harness vía ACP (desacoplado), Saghet Matrix Control Center (10 módulos), 10 benchmarks reproducibles y documentación/ADRs.
