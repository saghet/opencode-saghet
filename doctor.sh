#!/usr/bin/env bash
set -euo pipefail

# OpenCode-Saghet — Diagnóstico integral del sistema (doctor.sh)
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CFG_DIR="${HOME}/.config/opencode"
FAIL=0

ok()   { printf "[OK]   %s\n" "$1"; }
warn() { printf "[WARN] %s\n" "$1"; }
err()  { printf "[FAIL] %s\n" "$1"; FAIL=1; }

echo "=== OpenCode-Saghet Doctor ==="

# 1. OS
if [ -f /etc/os-release ]; then
  . /etc/os-release
  ok "SO detectado: ${PRETTY_NAME:-$ID}"
else
  warn "No se encontró /etc/os-release"
fi

# 2. Herramientas base
for cmd in git node npm python3 sqlite3 psql docker; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "Herramienta disponible: $cmd ($(command -v "$cmd"))"
  else
    warn "Herramienta opcional/base ausente: $cmd"
  fi
done

for cmd in valkey-cli redis-cli; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "Cliente Redis/Valkey disponible: $cmd"
    break
  fi
done

# 3. GPU NVIDIA y CUDA
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  GPU_INFO="$(nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader | head -n1)"
  ok "GPU NVIDIA activa: $GPU_INFO"
else
  warn "nvidia-smi no disponible o GPU no detectada"
fi

# 4. Ollama
if command -v ollama >/dev/null 2>&1; then
  if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    MODELS_CNT="$(curl -sf http://127.0.0.1:11434/api/tags | python3 -c 'import sys,json; print(len(json.load(sys.stdin).get("models",[])))')"
    ok "Ollama activo ($(ollama --version | head -n1)), modelos locales: $MODELS_CNT"
  else
    err "Ollama instalado pero no responde en http://127.0.0.1:11434"
  fi
else
  err "Ollama no está instalado"
fi

# 5. OpenCode CLI y configuración
if command -v opencode >/dev/null 2>&1; then
  ok "OpenCode CLI: $(opencode --version)"
else
  err "OpenCode CLI no encontrado en PATH"
fi

for f in opencode.json tui.json dcp.jsonc opencode-mem.jsonc AGENTS.md themes/saghet-dark.json themes/saghet-light.json tui-plugins/saghet-tui/index.js; do
  if [ -e "${CFG_DIR}/${f}" ]; then
    ok "Config desplegada: ${CFG_DIR}/${f}"
  else
    err "Falta archivo desplegado: ${CFG_DIR}/${f}"
  fi
done

# 6. Servicio systemd del Control Center
if command -v systemctl >/dev/null 2>&1; then
  if systemctl --user is-enabled --quiet saghet-dashboard.service 2>/dev/null; then
    ok "Servicio saghet-dashboard.service habilitado en arranque"
  else
    warn "Servicio saghet-dashboard.service no habilitado (ejecuta ./install.sh)"
  fi
fi

# 7. Validación JSON de opencode.json
if [ -f "${CFG_DIR}/opencode.json" ]; then
  if python3 -m json.tool "${CFG_DIR}/opencode.json" >/dev/null 2>&1; then
    ok "opencode.json es JSON válido"
  else
    err "opencode.json contiene JSON inválido"
  fi
fi

# 7. Seguridad: verificar que no haya secretos rastreados en el repo
if git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  TRACKED_SECRETS="$(git -C "$REPO_DIR" ls-files | grep -E '(^\.env|\.env\.db$|service\.json$|\.auth-token$|\.key$|\.pem$)' || true)"
  if [ -z "$TRACKED_SECRETS" ]; then
    ok "Repositorio Git libre de archivos secretos rastreados"
  else
    err "Archivos sensibles rastreados en Git: $TRACKED_SECRETS"
  fi
fi

echo "=== Resultado Doctor: $([ "$FAIL" -eq 0 ] && echo 'SALUDABLE' || echo 'CON FALLOS') ==="
exit "$FAIL"
