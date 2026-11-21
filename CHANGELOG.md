# Changelog — OpenCode-Saghet

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
