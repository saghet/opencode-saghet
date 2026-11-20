# Arquitectura Visual — SAGHET // MATRIX PROTOCOL

> **Nota de transparencia:** No se adjuntaron imágenes de referencia externas en la sesión; el sistema visual se diseñó íntegramente a partir de la especificación técnica y estética **Matrix Protocol** definida para OpenCode-Saghet.

## 1. Sistema de Identidad Visual

- **Marca:** `OPENCODE-SAGHET`
- **Protocolo Visual:** `SAGHET // MATRIX PROTOCOL`
- **Paleta Oficial:**
  - Negro principal (`--bg`): `#030705`
  - Negro secundario (`--bg-sec`): `#080F0B`
  - Paneles translúcidos (`--panel`): `rgba(11, 21, 16, 0.86)` (`#0B1510`)
  - Verde principal (`--primary`): `#00FF66`
  - Verde secundario (`--secondary`): `#00C853`
  - Verde oscuro (`--dark-green`): `#064D2B`
  - Texto principal (`--text`): `#E5F5EA` (contraste > 15:1 sobre `#030705`)
  - Texto secundario (`--muted`): `#8BA596`
  - Bordes (`--border`): `#164B30`
  - Alertas (`--amber`): `#FFB020`
  - Errores (`--error`): `#FF4D6A`
- **Tipografía:**
  - Monoespaciada (HUD, código, títulos técnicos): `JetBrainsMono Nerd Font`, `JetBrains Mono`, `IBM Plex Mono`, `monospace`
  - Secundaria (descripciones y cuerpo): `Inter`, `system-ui`, `sans-serif`

## 2. Capas de Integración en OpenCode-Saghet

1. **TUI Nativo (`themes/saghet-dark.json`, `themes/saghet-light.json`, `plugins/saghet-tui/index.js`):**
   - Desplegado en `~/.config/opencode/themes/` y `~/.config/opencode/tui-plugins/saghet-tui/`.
   - No modifica el binario `/usr/bin/opencode` ni `/usr/lib/opencode-desktop/app.asar` (preserva actualizaciones `pacman`).
2. **Saghet Matrix Control Center v2 (`dashboard/` — 10 Módulos Especializados):**
   - Servidor local Python blindado con seguridad P0 (`127.0.0.1:4780`, Auth Token 256-bit, Anti-CSRF, Anti-DNS Rebinding) conectado en tiempo real (`< 40 ms` vía SQLite RO) a:
     - OpenCode v2 API / SQLite (`opencode.db`, `127.0.0.1:49374`) y `opencode acp`
     - Gentle AI v4.5.0, Supervisor de Calidad (`quality_supervisor.py`), `SmartModelRouter` (`model_lab.py`), Memoria Jerárquica (`hierarchical_memory.py`) y Adaptador DeepSeek Harness ACP (`workflow_engine.py`)
     - Ollama (`127.0.0.1:11434/api/ps`, `/api/tags`), GPU NVIDIA (`nvidia-smi`), CPU (`/proc/stat`) y RAM (`/proc/meminfo`)
     - Los 10 módulos visuales: *1. Agent Command Center*, *2. Model Intelligence*, *3. Workflow Orchestration (DAG)*, *4. Task Board*, *5. Session Inspector*, *6. Memory Explorer*, *7. Performance Lab*, *8. Security Center*, *9. Benchmark Center* y *10. Integration Manager*.
3. **Recursos Gráficos (`assets/matrix/`):**
   - `saghet-logo.svg`, `saghet-symbol.svg`, `app-icon.svg`, `matrix-bg.svg`, `agent-states.svg`.
   - Icono instalado en `~/.local/share/icons/hicolor/scalable/apps/opencode-saghet.svg`.

## 3. Motor Matrix Rain (`dashboard/matrix-rain.js`)

- Implementado en **Canvas 2D** con caracteres Katakana, hexadecimales y símbolos.
- Límite de FPS configurable (24 FPS por defecto; 15/24/30/60).
- Pausa automática cuando `document.visibilityState === "hidden"`.
- Respeta `prefers-reduced-motion: reduce`.
- Atenuación automática fuera de la pantalla de inicio (`0.48` en Inicio vs `0.10` en Sesiones/Configuración/Código).
