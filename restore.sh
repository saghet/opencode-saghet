#!/usr/bin/env bash
set -euo pipefail

# OpenCode-Saghet — Restauración desde copia de seguridad
CFG_DIR="${HOME}/.config/opencode"
BACKUPS_ROOT="${CFG_DIR}/backups"

if [ ! -d "$BACKUPS_ROOT" ]; then
  echo "[FAIL] No existe directorio de respaldos: $BACKUPS_ROOT"
  exit 1
fi

if [ "${1:-}" = "--list" ] || [ -z "${1:-}" ]; then
  echo "Respaldos disponibles en ${BACKUPS_ROOT}:"
  ls -1dt "${BACKUPS_ROOT}"/*/ 2>/dev/null | xargs -r -n1 basename
  echo ""
  echo "Uso: ./restore.sh <nombre_respaldo>"
  exit 0
fi

TARGET="${BACKUPS_ROOT}/$1"
if [ ! -d "$TARGET" ]; then
  echo "[FAIL] Respaldo no encontrado: $TARGET"
  exit 1
fi

SAFETY_SNAP="${BACKUPS_ROOT}/pre_restore_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$SAFETY_SNAP"
for item in opencode.json tui.json dcp.jsonc opencode-mem.jsonc AGENTS.md dbhub.toml; do
  [ -e "${CFG_DIR}/${item}" ] && cp -a "${CFG_DIR}/${item}" "${SAFETY_SNAP}/"
done

cp -a "${TARGET}/." "${CFG_DIR}/"
opencode reload >/dev/null 2>&1 || true
echo "[OK] Restaurado desde ${TARGET} (respaldo previo en ${SAFETY_SNAP})"
