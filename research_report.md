# Informe de Investigación y Estado Arquitectónico — OpenCode-Saghet (`v0.2.0-matrix-nextgen`)

## 1. Resumen Ejecutivo
**OpenCode-Saghet // MATRIX PROTOCOL (`v0.2.0-matrix-nextgen`)** es una plataforma autónoma local-first sobre **OpenCode v2.3.2**, **Gentle AI v4.5.0**, **Ollama 0.40.16** y un **Adaptador Desacoplado DeepSeek Harness vía ACP**, utilizando un coordinador principal (`saghet-orchestrator`) que orquesta **17 perfiles especializados** (13 principales + 4 bajo demanda) sobre hardware **NVIDIA GeForce RTX 4060 Laptop (8188 MiB VRAM)** y **32 GiB RAM** en **Garuda / Arch Linux**.

### Capacidades Clave Verificadas en Producción
- **Regla de Modelo Único en VRAM (`OLLAMA_MAX_LOADED_MODELS=1`):** Alineación completa entre OpenCode y `opencode-mem` (`qwen3.5:9b`), eliminando expulsiones cruzadas de VRAM.
- **Supervisor Inteligente de Calidad (`scripts/supervisor/quality_supervisor.py`):** Verificación independiente obligatoria, detección de errores de razonamiento y contradicciones, prohibición de entregas sin evidencia real, límite de 2 reintentos controlados (`max_iterations=3`) y aislamiento por `git worktree` (`scripts/supervisor/worktree_manager.py`).
- **Gentle AI v4.5.0 Active Bridge + SmartModelRouter (`scripts/eval/model_lab.py`):** Evaluación sobre 12 métricas verificables (`benchmarks/model_evaluation_matrix.json`) y enrutamiento consciente del costo de cambio de modelo en 8 GB VRAM.
- **Memoria Jerárquica de 4 Niveles (`scripts/memory/hierarchical_memory.py`):** Niveles `session`, `project`, `experience` y `user` con procedencia, fecha, contexto, confianza (`0.0–1.0`), deduplicación y filtro de relevancia, junto con `dcp.jsonc` (`protectUserMessages: true`).
- **Adaptador Desacoplado DeepSeek Harness vía ACP (`scripts/harness/`):** Workflows DAG, Task Board, sesiones persistentes, Execution Traces append-only y recuperación de fallos sobre JSON-RPC 2.0 (`opencode acp`) sin incorporar Cordis en el núcleo (`cordis_in_core: false`).
- **Saghet Matrix Control Center v2 (`dashboard/`):** 10 módulos visuales con blindaje P0 (Token Auth 256-bit, Anti-CSRF, Anti-DNS Rebinding, allowlists, `os.killpg` y `audit.log`) y latencia de telemetría `< 40 ms`.
- **Laboratorio de 10 Benchmarks Reproducibles (`tests/benchmarks/run_intelligence_benchmarks.py`):** `10/10` escenarios superados (`100.0 %`) en proyectos Git aislados sin mutaciones artificiales desde los tests (`peak_vram_mib: 6568.0 MiB`).

---

## 2. Documentación de Referencia en el Repositorio

- [Arquitectura Técnica y Diagramas Mermaid](docs/ARCHITECTURE.md)
- [Matriz de Funcionalidades Verificadas](docs/FEATURE_MATRIX.md)
- [Informe de Seguridad P0 y Resultados de Benchmarks](docs/SECURITY_AND_BENCHMARK_REPORT.md)
- [Manual de Instalación y Configuración](docs/INSTALLATION_AND_CONFIG_MANUAL.md)
- [Guía de Actualización y Plan de Mantenimiento](docs/UPGRADE_AND_MAINTENANCE_GUIDE.md)
- [Inventario de Extensiones, Plugins, MCP y Skills](docs/EXTENSIONS_INVENTORY.md)
