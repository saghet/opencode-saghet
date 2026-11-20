# OpenCode-Saghet // MATRIX PROTOCOL

Distribución personalizada, reproducible y optimizada de desarrollo con IA para **Garuda / Arch Linux** sobre **OpenCode v2.3.2** y **Ollama**, diseñada para ejecución local-first en GPU **NVIDIA RTX 4060 Laptop (8 GB VRAM)** y **32 GB RAM**.

## Identidad Visual: SAGHET // MATRIX PROTOCOL

- **Saghet Control Center (`dashboard/`):** Interfaz web Matrix Protocol (`#030705`, `#0B1510`, `#00FF66`) con lluvia digital Canvas 2D optimizada (FPS configurable, pausa automática en segundo plano y soporte `prefers-reduced-motion`), consola de ejecución de prompts, inspector de sesiones/código, matriz de agentes, explorador de proyectos, Ollama/VRAM en tiempo real y diagnóstico integrado.
- **Temas TUI y Plugin (`themes/`, `plugins/saghet-tui/`):** Temas nativos `saghet-dark` (Matrix Protocol) y `saghet-light`, junto al plugin `@opencode/plugin/tui` con comandos rápidos de estado.
- **Recursos Vectoriales (`assets/matrix/`):** Logotipo, símbolo hexagonal Saghet, icono de aplicación (`opencode-saghet.svg`), retícula de fondo y estados de agentes.

## Características Principales

- **Sistema Multiagente (13+ Especialistas):** `saghet-orchestrator`, `architect`, `researcher`, `senior-developer`, `frontend-specialist`, `backend-specialist`, `database-specialist`, `devops-engineer`, `security-auditor`, `code-reviewer`, `qa-engineer`, `performance-engineer` y `documentation-engineer`, con permisos diferenciados y aislamiento por `git worktree`.
- **Optimización CUDA / VRAM (8 GB):** Regla de modelo único activo en GPU (`OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`), benchmarks reales en [benchmarks/rtx4060_saghet.json](benchmarks/rtx4060_saghet.json) y cadena de fallback automático.
- **Extensiones Fijadas:** `@tarquinen/opencode-dcp@3.2.1`, `opencode-mem@2.43.0`, `@plannotator/opencode@0.29.0`, `dbhub@1.7.1`, `sequential-thinking@2.2.0` y `context7`.
- **Seguridad por Defecto:** Bloqueo de lectura/edición sobre `.env*`, `service.json`, `*.key`, `*.pem`, `.ssh/*`; confirmación para operaciones destructivas y auditoría sin secretos en Git.

## Instalación Rápida en Garuda / Arch Linux

```bash
git clone https://github.com/saghet/opencode-saghet.git
cd opencode-saghet
./install.sh
```

Opciones útiles:
- `./install.sh --dry-run` — Simula el proceso sin modificar archivos.
- `./install.sh --skip-models` — Despliega configuración, temas, iconos y plugins sin descargar modelos de Ollama.
- `./doctor.sh` — Verifica SO, GPU, Ollama, OpenCode, configuraciones y limpieza de secretos.
- `./update.sh` — Actualiza y re-aplica la distribución de forma idempotente.
- `./restore.sh --list` / `./restore.sh <snapshot>` — Restaura copias de seguridad previas.
- `./uninstall.sh` — Retira la capa Saghet generando un respaldo previo.

## Saghet Control Center

```bash
opencode-saghet --dashboard
# o manualmente:
python3 dashboard/server.py --port 4780
# Abrir http://127.0.0.1:4780
```

## Pruebas de Aceptación

```bash
python3 tests/run_acceptance.py
```

## Documentación

- [Arquitectura Técnica](docs/ARCHITECTURE.md)
- [Arquitectura Visual — Matrix Protocol](docs/VISUAL_ARCHITECTURE.md)
- [Inventario de Extensiones, Plugins, MCP y Skills](docs/EXTENSIONS_INVENTORY.md)
- [Matriz de Compatibilidad y Versiones Fijadas](compatibility.json)
- [Atribuciones y Licencias](NOTICE.md)
