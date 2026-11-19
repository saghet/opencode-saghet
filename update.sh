#!/usr/bin/env bash
set -euo pipefail

# OpenCode-Saghet — Actualizador seguro preservando configuraciones locales
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[SAGHET] Verificando compatibilidad..."
python3 -m json.tool "${REPO_DIR}/compatibility.json" >/dev/null

if git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if [ -n "$(git -C "$REPO_DIR" status --porcelain)" ]; then
    echo "[SAGHET] AVISO: Hay cambios locales sin commit; omitiendo git pull."
  else
    git -C "$REPO_DIR" pull --ff-only || true
  fi
fi

echo "[SAGHET] Re-aplicando distribución de forma idempotente (sin re-descargar modelos)..."
bash "${REPO_DIR}/install.sh" --skip-models
