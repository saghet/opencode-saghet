#!/usr/bin/env bash
set -euo pipefail

# OpenCode-Saghet — Instalador idempotente para Garuda / Arch Linux
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CFG_DIR="${HOME}/.config/opencode"
BACKUP_DIR="${CFG_DIR}/backups/install_$(date +%Y%m%d_%H%M%S)"
DRY_RUN=0
SKIP_MODELS=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --skip-models) SKIP_MODELS=1 ;;
    -h|--help)
      echo "Uso: ./install.sh [--dry-run] [--skip-models]"
      exit 0
      ;;
  esac
done

log() { printf "[SAGHET] %s\n" "$1"; }

log "1/8 Detectando distribución Linux..."
if [ -f /etc/os-release ]; then
  . /etc/os-release
  log "Distribución: ${PRETTY_NAME:-$ID}"
fi

log "2/8 Verificando dependencias del sistema..."
MISSING_PKGS=()
command -v git >/dev/null 2>&1 || MISSING_PKGS+=(git)
command -v node >/dev/null 2>&1 || MISSING_PKGS+=(nodejs npm)
command -v python3 >/dev/null 2>&1 || MISSING_PKGS+=(python)
command -v sqlite3 >/dev/null 2>&1 || MISSING_PKGS+=(sqlite)
command -v opencode >/dev/null 2>&1 || MISSING_PKGS+=(opencode)

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
  log "Paquetes faltantes detectados: ${MISSING_PKGS[*]}"
  if [ "$DRY_RUN" -eq 0 ] && command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --needed --noconfirm "${MISSING_PKGS[@]}"
  fi
fi

log "3/8 Verificando GPU NVIDIA y CUDA..."
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader | head -n1
else
  log "AVISO: No se detectó GPU NVIDIA activa; Ollama usará CPU si está disponible."
fi

log "4/8 Creando copia de seguridad previa (idempotente)..."
if [ "$DRY_RUN" -eq 0 ] && [ -d "$CFG_DIR" ]; then
  mkdir -p "$BACKUP_DIR"
  for item in opencode.json tui.json dcp.jsonc opencode-mem.jsonc AGENTS.md dbhub.toml themes tui-plugins skills; do
    if [ -e "${CFG_DIR}/${item}" ]; then
      cp -a "${CFG_DIR}/${item}" "${BACKUP_DIR}/"
    fi
  done
  log "Respaldo guardado en ${BACKUP_DIR}"
fi

log "5/8 Desplegando configuraciones, temas, TUI plugin y skills..."
if [ "$DRY_RUN" -eq 0 ]; then
  mkdir -p "${CFG_DIR}/themes" "${CFG_DIR}/tui-plugins/saghet-tui" "${CFG_DIR}/skills" "${HOME}/.opencode-mem/data"
  cp -a "${REPO_DIR}/themes/saghet-dark.json" "${CFG_DIR}/themes/"
  cp -a "${REPO_DIR}/themes/saghet-light.json" "${CFG_DIR}/themes/"
  cp -a "${REPO_DIR}/plugins/saghet-tui/package.json" "${CFG_DIR}/tui-plugins/saghet-tui/"
  cp -a "${REPO_DIR}/plugins/saghet-tui/index.js" "${CFG_DIR}/tui-plugins/saghet-tui/"
  cp -a "${REPO_DIR}/config/AGENTS.md" "${CFG_DIR}/AGENTS.md"
  cp -a "${REPO_DIR}/config/dcp.jsonc" "${CFG_DIR}/dcp.jsonc"

  for pair in "opencode-mem.jsonc:opencode-mem.jsonc" "tui.json:tui.json" "opencode.json.tpl:opencode.json"; do
    src="${pair%%:*}"
    dst="${pair##*:}"
    sed "s|__SAGHET_HOME__|${HOME}|g" "${REPO_DIR}/config/${src}" > "${CFG_DIR}/${dst}"
  done
  chmod 600 "${CFG_DIR}/opencode.json"

  if [ ! -f "${CFG_DIR}/.saghet-dashboard-token" ]; then
    python3 -c 'import secrets; print(secrets.token_hex(32))' > "${CFG_DIR}/.saghet-dashboard-token"
  fi
  chmod 600 "${CFG_DIR}/.saghet-dashboard-token"

  if [ -f "${REPO_DIR}/config/saghet-dashboard.service.tpl" ]; then
    mkdir -p "${HOME}/.config/systemd/user"
    sed "s|__SAGHET_REPO__|${REPO_DIR}|g" "${REPO_DIR}/config/saghet-dashboard.service.tpl" > "${HOME}/.config/systemd/user/saghet-dashboard.service"
    if command -v systemctl >/dev/null 2>&1; then
      systemctl --user daemon-reload >/dev/null 2>&1 || true
      systemctl --user enable --now saghet-dashboard.service >/dev/null 2>&1 || true
    fi
  fi

  if [ ! -f "${CFG_DIR}/dbhub.toml" ]; then
    sed "s|__SAGHET_HOME__|${HOME}|g" "${REPO_DIR}/config/dbhub.toml.tpl" > "${CFG_DIR}/dbhub.toml"
  fi

  for s in worktree-isolation db-safe-ops security-checklist multiagent-workflow; do
    mkdir -p "${CFG_DIR}/skills/${s}"
    cp -a "${REPO_DIR}/skills/${s}/SKILL.md" "${CFG_DIR}/skills/${s}/SKILL.md"
  done

  if [ -d "${REPO_DIR}/commands" ]; then
    mkdir -p "${CFG_DIR}/commands"
    cp -a "${REPO_DIR}/commands/"*.md "${CFG_DIR}/commands/"
  fi

  if [ -x "${HOME}/.cargo/bin/gentle-ai" ] || command -v gentle-ai >/dev/null 2>&1; then
    GENTLE_BIN="${HOME}/.cargo/bin/gentle-ai"
    command -v gentle-ai >/dev/null 2>&1 && GENTLE_BIN="$(command -v gentle-ai)"
    DO_NOT_TRACK=1 GENTLE_AI_TELEMETRY=0 "$GENTLE_BIN" skill-registry refresh --quiet --no-gitignore --cwd "${REPO_DIR}" >/dev/null 2>&1 || true
  fi

  mkdir -p "${HOME}/.local/bin" "${HOME}/.local/share/applications"
  sed "s|__SAGHET_REPO__|${REPO_DIR}|g" "${REPO_DIR}/scripts/opencode-saghet" > "${HOME}/.local/bin/opencode-saghet"
  chmod +x "${HOME}/.local/bin/opencode-saghet"

  if [ -f /usr/lib/opencode-desktop/app.asar ] && command -v electron44 >/dev/null 2>&1; then
    bash "${REPO_DIR}/scripts/build-desktop-matrix.sh" || true
  fi

  cat > "${HOME}/.local/share/applications/ai.opencode.desktop.desktop" << DESK
[Desktop Entry]
Name=OpenCode-Saghet
Comment=OpenCode-Saghet // Matrix Protocol AI Development Distribution
Exec=${HOME}/.local/bin/opencode-saghet --desktop %U
Terminal=false
Type=Application
Icon=ai.opencode.desktop
StartupWMClass=ai.opencode.desktop
MimeType=x-scheme-handler/opencode;
Categories=Development;
DESK

  cat > "${HOME}/.local/share/applications/opencode-saghet-dashboard.desktop" << DESK
[Desktop Entry]
Name=OpenCode-Saghet Control Center
Comment=Panel visual de agentes, modelos, VRAM/CUDA y telemetría
Exec=${HOME}/.local/bin/opencode-saghet --dashboard
Terminal=false
Type=Application
Icon=ai.opencode.desktop
Categories=Development;
DESK

  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "${HOME}/.local/share/applications" >/dev/null 2>&1 || true
fi

log "6/8 Verificando Ollama y modelos locales..."
if [ "$DRY_RUN" -eq 0 ] && [ "$SKIP_MODELS" -eq 0 ] && command -v ollama >/dev/null 2>&1; then
  AVAIL_KB="$(df -Pk "${HOME}" | awk 'NR==2 {print $4}')"
  if [ "${AVAIL_KB:-0}" -lt 20971520 ]; then
    log "AVISO: Menos de 20 GiB libres en ${HOME}; omitiendo descarga automática de modelos."
  else
    for m in qwen3.5:4b qwen3.5:9b qwen2.5-coder:7b abliterant/qwen3.5-rana:9b; do
      if ! ollama list 2>/dev/null | awk '{print $1}' | grep -Fxq "$m"; then
        log "Descargando modelo $m..."
        ollama pull "$m"
      else
        log "Modelo ya presente: $m"
      fi
    done
  fi
fi

log "7/8 Recargando OpenCode..."
if [ "$DRY_RUN" -eq 0 ] && command -v opencode >/dev/null 2>&1; then
  opencode reload >/dev/null 2>&1 || true
fi

log "8/8 Ejecutando diagnóstico final..."
if [ "$DRY_RUN" -eq 0 ]; then
  bash "${REPO_DIR}/doctor.sh"
else
  log "Dry-run completado sin modificaciones."
fi
