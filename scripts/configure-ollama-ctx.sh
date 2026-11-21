#!/usr/bin/env bash
set -euo pipefail

# OpenCode-Saghet — Configurador idempotente de contexto físico en Ollama (24576 tokens)
# Asegura que los modelos residentes tengan PARAMETER num_ctx 24576 en su Modelfile
# para superar el fallback de OLLAMA_CONTEXT_LENGTH=16384 sin duplicar blobs en disco.

TARGET_CTX="${1:-24576}"
MODELS=("qwen3.5:9b" "qwen3.5:4b" "abliterant/qwen3.5-rana:9b")

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
