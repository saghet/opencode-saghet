#!/usr/bin/env bash
set -euo pipefail

# OpenCode-Saghet — Construye el wrapper visual Matrix para opencode-desktop
# No modifica /usr/lib/opencode-desktop/app.asar (preserva actualizaciones de pacman).

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASAR_SRC="/usr/lib/opencode-desktop/app.asar"
BASE_DIR="${HOME}/.local/share/opencode-saghet"
WRAP_DIR="${BASE_DIR}/wrapper"
OVERLAY_SRC="${REPO_DIR}/assets/matrix/desktop-matrix-overlay.js"

if [ ! -f "$ASAR_SRC" ]; then
  echo "[ERROR] No se encontró $ASAR_SRC" >&2
  exit 1
fi

mkdir -p "$WRAP_DIR"

cat > "${WRAP_DIR}/package.json" << 'JSON'
{
  "name": "@opencode/desktop",
  "private": true,
  "version": "2.3.2",
  "type": "module",
  "main": "./bootstrap.mjs"
}
JSON

cat > "${WRAP_DIR}/bootstrap.mjs" << 'JS'
import { app } from "electron";
import fs from "node:fs";
import path from "node:path";

Object.defineProperty(app, "isPackaged", { get: () => true });
if (typeof app.setAppPath === "function") {
  app.setAppPath("/usr/lib/opencode-desktop/app.asar");
}

const OVERLAY_PATH = path.join(import.meta.dirname, "desktop-matrix-overlay.js");
app.on("browser-window-created", (_event, win) => {
  const inject = () => {
    try {
      const code = fs.readFileSync(OVERLAY_PATH, "utf8");
      win.webContents.executeJavaScript(code).catch(() => {});
    } catch {}
  };
  win.webContents.on("dom-ready", inject);
  win.webContents.on("did-finish-load", inject);
});

await import("/usr/lib/opencode-desktop/app.asar/out/main/index.js");
JS

cp -a "$OVERLAY_SRC" "${WRAP_DIR}/desktop-matrix-overlay.js"
echo "[SAGHET] Wrapper Matrix de escritorio desplegado en ${WRAP_DIR}"
