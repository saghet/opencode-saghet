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
2. **Saghet Control Center (`dashboard/`):**
   - Servidor local Python (`127.0.0.1:4780`) conectado en tiempo real a:
     - OpenCode v2 API (`opencode api ...` / `127.0.0.1:49374`)
     - Ollama (`127.0.0.1:11434/api/ps`, `/api/tags`)
     - GPU NVIDIA (`nvidia-smi`), CPU (`/proc/stat`, `/proc/loadavg`) y RAM (`/proc/meminfo`)
     - Benchmarks reales (`benchmarks/rtx4060_saghet.json`) y diagnóstico (`doctor.sh`)
3. **Recursos Gráficos (`assets/matrix/`):**
   - `saghet-logo.svg`, `saghet-symbol.svg`, `app-icon.svg`, `matrix-bg.svg`, `agent-states.svg`.
   - Icono instalado en `~/.local/share/icons/hicolor/scalable/apps/opencode-saghet.svg`.

## 3. Motor Matrix Rain (`dashboard/matrix-rain.js`)

- Implementado en **Canvas 2D** con caracteres Katakana, hexadecimales y símbolos.
- Límite de FPS configurable (24 FPS por defecto; 15/24/30/60).
- Pausa automática cuando `document.visibilityState === "hidden"`.
- Respeta `prefers-reduced-motion: reduce`.
- Atenuación automática fuera de la pantalla de inicio (`0.48` en Inicio vs `0.10` en Sesiones/Configuración/Código).
