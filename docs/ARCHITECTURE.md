# Arquitectura Técnica — OpenCode-Saghet

## 1. Visión General

**OpenCode-Saghet** es una distribución personalizada, reproducible y optimizada de desarrollo asistido por IA sobre **OpenCode v2.3.2** para **Garuda Linux / Arch Linux**, diseñada específicamente para hardware local con GPU **NVIDIA RTX 4060 Laptop (8188 MiB VRAM)**, **AMD Ryzen 9 7940HS** y **32 GiB RAM**.

## 2. Estructura del Repositorio

```text
OpenCode-Saghet/
├── compatibility.json          # Matriz de versiones y commits fijados
├── LICENSE / NOTICE.md         # Licencias y atribuciones upstream (MIT / Apache-2.0)
├── config/                     # Plantillas reproducibles (sin secretos)
│   ├── opencode.json.tpl       # Configuración principal de agentes, modelos, MCP y seguridad
│   ├── tui.json                # Configuración TUI y plugin de estado
│   ├── dcp.jsonc               # Dynamic Context Pruning (3.2.1)
│   ├── opencode-mem.jsonc      # Memoria persistente local (2.43.0)
│   ├── dbhub.toml.tpl          # Fuentes SQLite/PostgreSQL (placeholders de entorno)
│   └── AGENTS.md               # Contrato operativo multiagente
├── themes/                     # Identidad visual Saghet (oscuro por defecto + claro)
│   ├── saghet-dark.json
│   └── saghet-light.json
├── plugins/                    # Plugins propios de Saghet para OpenCode v2
│   └── saghet-tui/             # Plugin TUI (@opencode/plugin/tui + OpenTUI >= 0.7)
├── dashboard/                  # Saghet Control Center (Web UI sobre API v2 de OpenCode)
├── skills/                     # Skills reutilizables (worktree-isolation, db-safe-ops, etc.)
├── commands/                   # Comandos slash personalizados
├── scripts/                    # Ciclo de vida e infraestructura
│   ├── install.sh              # Instalador idempotente para Garuda/Arch Linux
│   ├── update.sh               # Actualizador seguro preservando configuraciones locales
│   ├── uninstall.sh            # Desinstalación limpia con opción de respaldo
│   ├── restore.sh              # Restauración desde snapshot
│   ├── doctor.sh               # Diagnóstico integral (OS, GPU, CUDA, Ollama, MCP, BD)
│   └── telemetry/              # Benchmarks y monitorización VRAM/RAM/tok/s
├── tests/                      # Pruebas automatizadas (contrato, seguridad, integración)
├── benchmarks/                 # Líneas base y comparativas antes/después
└── docs/                       # Documentación técnica, ADRs y guías
```

## 3. Estrategia de Sincronización con Upstream (`anomalyco/opencode`)

1. **Separación Motor vs. Distribución:** OpenCode `v2.3.2` se instala como paquete del sistema (`opencode` en Arch/Garuda) o binario fijado, evitando parches invasivos en el núcleo salvo que sean estrictamente necesarios.
2. **Capa Declarativa Saghet:** Toda la personalización (temas, plugins TUI, agentes, permisos, MCP, dashboard vía API v2) reside en capas estándar soportadas por OpenCode v2 (`~/.config/opencode/` y servicio web independiente sobre `127.0.0.1:49374`).
3. **Actualización Segura:** `update.sh` valida `compatibility.json` antes de actualizar paquetes, crea un snapshot automático en `~/.config/opencode/backups/` y ejecuta `doctor.sh` tras aplicar cambios.

## 4. Arquitectura Visual (Identidad Saghet)

> **Nota de transparencia:** No se encontró ningún código de referencia previo llamado `opencode-saghet` en el sistema; la identidad visual se diseña desde cero con criterios profesionales y minimalistas.

- **Capa 1 (TUI Nativo):** Temas `saghet-dark.json` (predeterminado) y `saghet-light.json` + plugin `saghet-tui` para barra de estado de agente/modelo, indicadores de tokens y comandos rápidos.
- **Capa 2 (Saghet Control Center):** Frontend web único conectado al servidor oficial v2 de OpenCode (`127.0.0.1:49374`), Ollama (`/api/ps`, `/api/tags`) y `nvidia-smi`, ofreciendo:
  - Panel de agentes y estado de ejecución.
  - Visualización de tareas y delegaciones.
  - Consumo de tokens y métricas de VRAM/RAM/tok/s.
  - Estado de herramientas, plugins y MCP.
  - Panel de proveedores y conmutador de tema oscuro/claro.
  - Sin interfaces web redundantes.

## 5. Arquitectura Multiagente (13 Especialistas)

| # | Agente | Modo | Modelo Asignado | Permisos | Rol Principal |
| :-: | :--- | :--- | :--- | :--- | :--- |
| 1 | `saghet-orchestrator` | `primary` | `ollama/qwen3.5:9b` | Completo (con guardrails) | Coordinador principal, enrutamiento y gates A–F |
| 2 | `architect` | `subagent` | `ollama/qwen3.5:9b` | Solo lectura | Arquitectura modular, contratos, ADRs |
| 3 | `researcher` | `subagent` | `ollama/qwen3.5:9b` | Solo lectura + `context7` | Investigación técnica, repositorios y docs |
| 4 | `senior-developer` | `subagent` | `ollama/qwen3.5:9b` | Lectura/Escritura/Bash | Implementación general y refactorización |
| 5 | `frontend-specialist` | `subagent` | `ollama/qwen3.5:9b` | Lectura/Escritura/Bash | UI/UX, React/TS, CSS, accesibilidad |
| 6 | `backend-specialist` | `subagent` | `ollama/qwen3.5:9b` | Lectura/Escritura/Bash | APIs, servicios, colas y lógica de negocio |
| 7 | `database-specialist` | `subagent` | `ollama/qwen3.5:9b` | Lectura/Escritura/Bash + `dbhub` | PostgreSQL, SQLite, Redis/Valkey, migraciones |
| 8 | `devops-engineer` | `subagent` | `ollama/qwen3.5:9b` | Lectura/Escritura/Bash | Arch/Garuda, systemd, Docker, CI/CD, worktrees |
| 9 | `security-auditor` | `subagent` | `ollama/abliterant/qwen3.5-rana:9b` | Solo lectura | Auditoría estática, secretos, CVEs |
| 10 | `code-reviewer` | `subagent` | `ollama/qwen3.5:9b` | Solo lectura | Revisión independiente de calidad y diffs |
| 11 | `qa-engineer` | `subagent` | `ollama/qwen3.5:9b` | Lectura/Escritura/Bash | Pruebas unitarias, integración, E2E y regresión |
| 12 | `performance-engineer` | `subagent` | `ollama/qwen3.5:9b` | Lectura/Escritura/Bash | Profiling, benchmarks, CUDA/VRAM y optimización |
| 13 | `documentation-engineer` | `subagent` | `ollama/qwen3.5:9b` | Lectura/Escritura (sin Bash) | Manuales, ADRs, diagramas Mermaid |

**Regla de Concurrencia Local:** Con `OLLAMA_MAX_LOADED_MODELS=1`, las delegaciones que usan modelos locales se ejecutan **secuencialmente** para evitar expulsiones de VRAM; la ejecución paralela controlada se reserva para herramientas/subprocesos sin carga simultánea de múltiples LLMs en GPU o cuando se usan proveedores externos configurados por el usuario.

## 6. Política de Seguridad por Defecto

- **Secretos:** `.env*`, `*.key`, `*.pem`, `*.p12`, `.ssh/**`, `.aws/credentials`, `service.json`, `.auth-token` bloqueados en lectura/edición de agentes y excluidos en `.gitignore`.
- **Operaciones destructivas:** `rm -rf` sobre rutas raíz/home bloqueado (`deny`); `git push --force`, `git reset --hard`, `git clean -f` bloqueados (`deny`); `DROP`/`TRUNCATE`/`DELETE` masivo y `git push` requieren confirmación (`ask`).
- **Aislamiento:** Cambios de alto riesgo aislados mediante `git worktree` (skill `worktree-isolation`).
- **Cadena de suministro:** Todas las versiones de plugins y MCP fijadas en `compatibility.json` (sin `@latest` en producción).
