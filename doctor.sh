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

# 7. Validación JSON de opencode.json, VRAM alignment y políticas DCP/Seguridad
if [ -f "${CFG_DIR}/opencode.json" ]; then
  if python3 -m json.tool "${CFG_DIR}/opencode.json" >/dev/null 2>&1; then
    ok "opencode.json es JSON válido"
  else
    err "opencode.json contiene JSON inválido"
  fi
fi

if [ -f "${CFG_DIR}/dcp.jsonc" ] && grep -q '"protectUserMessages": true' "${CFG_DIR}/dcp.jsonc"; then
  ok "DCP protege mensajes del usuario (protectUserMessages: true)"
else
  err "DCP no tiene protectUserMessages: true en ${CFG_DIR}/dcp.jsonc"
fi

if [ -f "${CFG_DIR}/opencode-mem.jsonc" ] && grep -q '"opencodeModel": "qwen3.5:9b"' "${CFG_DIR}/opencode-mem.jsonc"; then
  ok "opencode-mem alineado en VRAM con modelo residente (qwen3.5:9b)"
else
  err "opencode-mem no está alineado con qwen3.5:9b (riesgo de colisión VRAM)"
fi

if [ -f "${CFG_DIR}/opencode-mem.jsonc" ] && grep -q '"autoCaptureEnabled": false' "${CFG_DIR}/opencode-mem.jsonc"; then
  ok "opencode-mem sin bloqueo StructuredOutput de 45s (autoCaptureEnabled: false)"
else
  warn "opencode-mem tiene autoCaptureEnabled: true (riesgo de timeout de 45s en StructuredOutput)"
fi

if [ -f "${CFG_DIR}/.saghet-dashboard-token" ]; then
  TOK_PERM="$(stat -c '%a' "${CFG_DIR}/.saghet-dashboard-token" 2>/dev/null || echo "")"
  if [ "$TOK_PERM" = "600" ]; then
    ok "Token de seguridad del Control Center presente con permisos 600"
  else
    err "Permisos inseguros en ${CFG_DIR}/.saghet-dashboard-token (${TOK_PERM})"
  fi
else
  warn "Token de seguridad ${CFG_DIR}/.saghet-dashboard-token aún no generado"
fi

if [ -f /etc/systemd/system/ollama.service.d/override.conf ] && grep -q 'OLLAMA_MAX_LOADED_MODELS=1' /etc/systemd/system/ollama.service.d/override.conf; then
  ok "Ollama override activo (OLLAMA_MAX_LOADED_MODELS=1, KV_CACHE=q8_0)"
else
  warn "No se detectó /etc/systemd/system/ollama.service.d/override.conf con OLLAMA_MAX_LOADED_MODELS=1"
fi

if [ -x "${HOME}/.cargo/bin/gentle-ai" ] || command -v gentle-ai >/dev/null 2>&1; then
  GENTLE_BIN="${HOME}/.cargo/bin/gentle-ai"
  command -v gentle-ai >/dev/null 2>&1 && GENTLE_BIN="$(command -v gentle-ai)"
  ok "Gentle AI activo: $($GENTLE_BIN --version 2>/dev/null | head -n1)"
else
  warn "Gentle AI CLI no detectado"
fi

if [ -d "${CFG_DIR}/commands" ] && grep -rq "gentle-orchestrator" "${CFG_DIR}/commands/" 2>/dev/null; then
  err "Comandos slash contienen referencia huérfana a gentle-orchestrator"
else
  ok "Comandos slash sincronizados con saghet-orchestrator"
fi

# 8. Seguridad: verificar que no haya secretos rastreados en el repo
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
