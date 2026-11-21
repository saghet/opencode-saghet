#!/usr/bin/env bash
set -euo pipefail

# OpenCode-Saghet — Configurador idempotente de contexto físico y anti-bucles en Ollama
# 1) Asegura PARAMETER num_ctx 24576 en la familia qwen3.5 sin duplicar blobs en disco.
# 2) Asegura PARAMETER num_ctx 16384, num_predict 2048 y repeat_penalty 1.15 en modelos deepseek-r1
#    para impedir bucles infinitos de pensamiento (<think>) de 15,000+ tokens.

TARGET_CTX="${1:-24576}"
MODELS=("qwen3.5:9b" "qwen3.5:4b" "abliterant/qwen3.5-rana:9b")
R1_MODELS=("deepseek-r1:8b" "huihui_ai/deepseek-r1-abliterated:8b-0528-qwen3")

if ! command -v ollama >/dev/null 2>&1; then
  exit 0
fi

INSTALLED_MODELS="$(ollama list 2>/dev/null | awk 'NR>1 {print $1}' || true)"
if [ -z "$INSTALLED_MODELS" ]; then
  exit 0
fi

for m in "${MODELS[@]}"; do
  if printf "%s\n" "$INSTALLED_MODELS" | grep -Fxq "$m"; then
    CURRENT_CTX="$(ollama show "$m" --modelfile 2>/dev/null | awk '/^PARAMETER num_ctx / {print $3}' | tail -n1 || true)"
    if [ "$CURRENT_CTX" != "$TARGET_CTX" ]; then
      TMP_MF="$(mktemp)"
      printf "FROM %s\nPARAMETER num_ctx %s\n" "$m" "$TARGET_CTX" > "$TMP_MF"
      ollama create "$m" -f "$TMP_MF" >/dev/null 2>&1 || true
      rm -f "$TMP_MF"
      printf "[SAGHET] Contexto físico en Ollama actualizado para %s -> num_ctx=%s\n" "$m" "$TARGET_CTX"
    fi
  fi
done

for m in "${R1_MODELS[@]}"; do
  if printf "%s\n" "$INSTALLED_MODELS" | grep -Fxq "$m"; then
    MF_OUT="$(ollama show "$m" --modelfile 2>/dev/null || true)"
    CUR_NP="$(printf "%s\n" "$MF_OUT" | awk '/^PARAMETER num_predict / {print $3}' | tail -n1 || true)"
    CUR_RP="$(printf "%s\n" "$MF_OUT" | awk '/^PARAMETER repeat_penalty / {print $3}' | tail -n1 || true)"
    if [ "$CUR_NP" != "2048" ] || [ "$CUR_RP" != "1.15" ]; then
      TMP_MF="$(mktemp)"
      printf "FROM %s\nPARAMETER num_ctx 16384\nPARAMETER num_predict 2048\nPARAMETER repeat_penalty 1.15\n" "$m" > "$TMP_MF"
      ollama create "$m" -f "$TMP_MF" >/dev/null 2>&1 || true
      rm -f "$TMP_MF"
      printf "[SAGHET] Anti-bucle Ollama actualizado para %s -> num_predict=2048, repeat_penalty=1.15\n" "$m"
    fi
  fi
done
