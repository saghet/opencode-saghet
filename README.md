# OpenCode-Saghet // MATRIX PROTOCOL (Next-Gen Engineering Upgrade `v0.2.0`)

Plataforma avanzada, local-first y autónoma de desarrollo con IA para **Garuda Linux y Arch Linux**, construida sobre **OpenCode v2.3.2**, **Gentle AI v4.5.0**, **Ollama 0.40.16**, **Saghet Matrix Control Center (10 módulos)** y **Adaptador Desacoplado DeepSeek Harness vía ACP**, optimizada para **NVIDIA GeForce RTX 4060 Laptop (8 GB VRAM)** y **32 GB RAM**.

---

## Arquitectura y Capacidades Principales

1. **Equipo de 17 Especialistas (13 Principales + 4 Bajo Demanda):**
   - **Principales:** `saghet-orchestrator`, `architect`, `researcher`, `senior-developer`, `frontend-specialist`, `backend-specialist`, `database-specialist`, `devops-engineer`, `security-auditor`, `code-reviewer`, `qa-engineer`, `performance-engineer` y `documentation-engineer`.
   - **Bajo Demanda:** `agent-evaluation-engineer`, `agent-observability-engineer`, `integration-architect` y `platform-security-engineer` (0 MiB de consumo adicional en reposo).
2. **Supervisor Inteligente de Calidad + Gentle AI v4.5.0 (`scripts/supervisor/`):**
   - Clasificación de complejidad y riesgo, verificación independiente obligatoria, detección de errores de razonamiento y contradicciones, prohibición de entregas sin evidencia real, límite de 2 reintentos controlados (`max_iterations=3`), aislamiento programático por `git worktree` con auto-rollback y registro auditable en `supervisor_decisions.jsonl`.
3. **Laboratorio de Evaluación de Modelos y Enrutamiento Basado en Evidencia (`scripts/eval/model_lab.py`):**
   - Evaluación sobre 12 métricas verificables (`benchmarks/model_evaluation_matrix.json`).
   - `SmartModelRouter` selecciona modelos por puntuación verificable y ajuste en los 8 GB de VRAM (`qwen3.5:4b` para clasificación fría, `qwen3.5:9b` para programación/arquitectura/memoria sin swap de VRAM, `abliterant/qwen3.5-rana:9b` para revisión independiente y seguridad).
4. **Memoria Jerárquica de 4 Niveles (`scripts/memory/hierarchical_memory.py`):**
   - Niveles `session`, `project`, `experience` y `user` con procedencia, fecha, contexto y nivel de confianza (`0.0–1.0`), deduplicación automática y filtro de relevancia, integrada con `opencode-mem@2.43.0` (alineado a `qwen3.5:9b`) y `opencode-dcp@3.2.1` (`protectUserMessages: true`).
5. **Adaptador Desacoplado DeepSeek Harness vía ACP (`scripts/harness/`):**
   - Orquestación opcional y conmutable (`config/harness.json`) de workflows **DAG**, **Task Board**, sesiones persistentes, **Execution Traces** y recuperación de fallos sobre JSON-RPC 2.0 (`opencode acp`), **sin incorporar Cordis en el núcleo** ni duplicar estado.
6. **Saghet Matrix Control Center v2 (`dashboard/` — 10 Módulos + Seguridad P0):**
   - **10 Módulos:** *1. Agent Command Center*, *2. Model Intelligence*, *3. Workflow Orchestration (DAG)*, *4. Task Board*, *5. Session Inspector*, *6. Memory Explorer*, *7. Performance Lab*, *8. Security Center*, *9. Benchmark Center* y *10. Integration Manager*.
   - **Blindaje P0:** Token de 256 bits (`~/.config/opencode/.saghet-dashboard-token`), cookie `HttpOnly; SameSite=Strict`, protección CSRF y DNS Rebinding (`Host`/`Origin`), allowlists de agentes/directorios, control de grupos de procesos (`os.killpg`) y bitácora `audit.log`.

---

## Instalación y Uso Rápido en Garuda / Arch Linux

```bash
git clone https://github.com/saghet/opencode-saghet.git
cd opencode-saghet
./install.sh
```

Comandos frecuentes:
- `./install.sh --skip-models` — Re-aplica configuración, comandos, skills y servicio `systemd --user` de forma idempotente.
- `./doctor.sh` — Diagnóstico integral de SO, GPU, Ollama, OpenCode, Gentle AI, VRAM alignment y seguridad P0.
- `opencode-saghet --dashboard` — Abre el **Saghet Matrix Control Center** (`http://127.0.0.1:4780`).
- `opencode-saghet --desktop` — Inicia OpenCode Desktop con overlay visual Matrix Protocol.
- `./update.sh` / `./restore.sh --list` — Actualización segura y restauración instantánea desde snapshots.

---

## Suite de Aceptación y Laboratorio de Benchmarks Reales

```bash
# 1. Suite de aceptación integral (Categorías A-N: instalación, agentes, seguridad P0, supervisor, memoria, harness, UI y docs)
python3 tests/run_acceptance.py

# 2. Laboratorio de 10 benchmarks reproducibles de inteligencia real en proyectos Git aislados
python3 tests/benchmarks/run_intelligence_benchmarks.py
```

---

## Documentación Técnica Completa

- [Arquitectura Técnica y Diagramas Mermaid](docs/ARCHITECTURE.md)
- [Matriz de Funcionalidades Verificadas](docs/FEATURE_MATRIX.md)
- [Arquitectura Visual — Matrix Protocol](docs/VISUAL_ARCHITECTURE.md)
- [Inventario de Extensiones, Plugins, MCP, Motores y Skills](docs/EXTENSIONS_INVENTORY.md)
- [Manual de Instalación y Configuración (Garuda / Arch Linux)](docs/INSTALLATION_AND_CONFIG_MANUAL.md)
- [Guía de Actualización y Plan de Mantenimiento](docs/UPGRADE_AND_MAINTENANCE_GUIDE.md)
- [Informe de Seguridad P0 y Resultados de Benchmarks](docs/SECURITY_AND_BENCHMARK_REPORT.md)
- **ADRs (Architecture Decision Records):**
  - [ADR-001: Política de Modelo Único en VRAM (8 GB RTX 4060) y Enrutamiento](docs/adr/ADR-001-vram-single-model-and-routing.md)
  - [ADR-002: Supervisor Inteligente de Calidad y Gentle AI v4.5.0](docs/adr/ADR-002-quality-supervisor-and-gentle-ai.md)
  - [ADR-003: Adaptador Desacoplado DeepSeek Harness vía ACP](docs/adr/ADR-003-decoupled-deepseek-harness-acp.md)
  - [ADR-004: Memoria Jerárquica de 4 Niveles y Protección DCP](docs/adr/ADR-004-hierarchical-memory-and-dcp.md)
  - [ADR-005: Blindaje de Seguridad P0 del Control Center](docs/adr/ADR-005-p0-platform-security-hardening.md)
- [Matriz de Compatibilidad y Versiones Fijadas](compatibility.json)
- [Atribuciones y Licencias](NOTICE.md)
