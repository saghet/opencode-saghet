#!/usr/bin/env bash
set -euo pipefail

# OpenCode-Saghet — Desinstalación limpia de la capa Saghet (con respaldo previo)
CFG_DIR="${HOME}/.config/opencode"
SNAP="${CFG_DIR}/backups/pre_uninstall_$(date +%Y%m%d_%H%M%S)"

if [ -d "$CFG_DIR" ]; then
  mkdir -p "$SNAP"
  for item in opencode.json tui.json dcp.jsonc opencode-mem.jsonc AGENTS.md themes tui-plugins; do
    [ -e "${CFG_DIR}/${item}" ] && cp -a "${CFG_DIR}/${item}" "${SNAP}/"
  done
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now saghet-dashboard.service >/dev/null 2>&1 || true
  fi
  rm -rf "${CFG_DIR}/tui-plugins/saghet-tui" \
         "${CFG_DIR}/themes/saghet-dark.json" \
         "${CFG_DIR}/themes/saghet-light.json" \
         "${HOME}/.local/bin/opencode-saghet" \
         "${HOME}/.config/systemd/user/saghet-dashboard.service" \
         "${HOME}/.local/share/applications/ai.opencode.desktop.desktop" \
         "${HOME}/.local/share/applications/opencode-saghet-dashboard.desktop"
  echo "[OK] Artefactos Saghet eliminados. Respaldo guardado en ${SNAP}."
  echo "Nota: Para restaurar tu configuración original, ejecuta: ./restore.sh 20261119_phase1_baseline"
fi
