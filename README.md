# OpenCode-Saghet

Distribución personalizada, reproducible y optimizada de desarrollo con IA para **Garuda / Arch Linux** sobre **OpenCode v2.3.2** y **Ollama**, diseñada para ejecución local-first en GPU **NVIDIA RTX 4060 Laptop (8 GB VRAM)** y **32 GB RAM**.

## Características Principales

- **Identidad Visual Saghet:** Temas nativos `saghet-dark` (predeterminado) y `saghet-light`, plugin TUI (`@opencode/plugin/tui`) y **Saghet Control Center** (`dashboard/server.py`) conectado en tiempo real al servidor v2 de OpenCode, Ollama y `nvidia-smi`.
- **Sistema Multiagente (13 Especialistas):** `saghet-orchestrator`, `architect`, `researcher`, `senior-developer`, `frontend-specialist`, `backend-specialist`, `database-specialist`, `devops-engineer`, `security-auditor`, `code-reviewer`, `qa-engineer`, `performance-engineer` y `documentation-engineer`, con permisos diferenciados y aislamiento por `git worktree`.
- **Optimización CUDA / VRAM (8 GB):** Regla de modelo único activo en GPU (`OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`), benchmarks reales en [benchmarks/rtx4060_saghet.json](benchmarks/rtx4060_saghet.json) y cadena de fallback automático.
- **Extensiones Fijadas:** `@tarquinen/opencode-dcp@3.2.1`, `opencode-mem@2.43.0`, `@plannotator/opencode@0.29.0`, `dbhub@1.7.1`, `sequential-thinking@2.2.0` y `context7`.
- **Seguridad por Defecto:** Bloqueo de lectura/edición sobre `.env*`, `service.json`, `*.key`, `*.pem`, `.ssh/*`; confirmación para operaciones destructivas y auditoría sin secretos en Git.

## Instalación Rápida en Garuda / Arch Linux

```bash
git clone <URL_DE_TU_FORK>/OpenCode-Saghet.git
cd OpenCode-Saghet
./install.sh
```

Opciones útiles:
- `./install.sh --dry-run` — Simula el proceso sin modificar archivos.
- `./install.sh --skip-models` — Despliega configuración, temas y plugins sin descargar modelos de Ollama.
- `./doctor.sh` — Verifica SO, GPU, Ollama, OpenCode, configuraciones y limpieza de secretos.
- `./update.sh` — Actualiza y re-aplica la distribución de forma idempotente.
- `./restore.sh --list` / `./restore.sh <snapshot>` — Restaura copias de seguridad previas.
- `./uninstall.sh` — Retira la capa Saghet generando un respaldo previo.

## Saghet Control Center

```bash
python3 dashboard/server.py --port 4780
# Abrir http://127.0.0.1:4780
```

## Pruebas de Aceptación

```bash
python3 tests/run_acceptance.py
```

## Documentación

- [Arquitectura Técnica](docs/ARCHITECTURE.md)
- [Inventario de Extensiones, Plugins, MCP y Skills](docs/EXTENSIONS_INVENTORY.md)
- [Matriz de Compatibilidad y Versiones Fijadas](compatibility.json)
- [Atribuciones y Licencias](NOTICE.md)
