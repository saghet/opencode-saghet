# ADR-001: Política de Modelo Único en VRAM (8 GB RTX 4060) y Enrutamiento Basado en Evidencia

- **Estado:** Aceptado y Verificado en Producción
- **Fecha:** 2026-11-20
- **Contexto:** El hardware objetivo es una GPU NVIDIA GeForce RTX 4060 Laptop con `8188 MiB` de VRAM física y `32 GiB` de RAM del sistema. Anteriormente, `opencode.json` utilizaba `qwen3.5:9b` (`6564 MiB` VRAM) mientras que `opencode-mem.jsonc` utilizaba `qwen2.5-coder:7b` (`5106 MiB` VRAM) bajo `OLLAMA_MAX_LOADED_MODELS=1`, provocando expulsiones constantes de pesos en GPU (thrashing de VRAM de 8–15 segundos por turno).
- **Decisión:**
  1. Mantener `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_FLASH_ATTENTION=1` y `OLLAMA_KV_CACHE_TYPE=q8_0`.
  2. Alinear `opencode-mem.jsonc` con `qwen3.5:9b` para compartir el modelo residente en VRAM con costo de cambio `0 ms`.
  3. Prohibir seleccionar modelos exclusivamente por cantidad de parámetros: `SmartModelRouter` ([scripts/eval/model_lab.py](file:///home/saghet/Documents/OpenCode-Saghet/scripts/eval/model_lab.py)) calcula una puntuación verificable sobre 12 métricas y penaliza cualquier modelo cuyo uso de VRAM supere el presupuesto seguro de `7800 MiB` (ej. `qwen3-coder:30b`).
  4. Reutilizar `qwen3.5:9b` para clasificación ligera cuando ya se encuentra cargado en VRAM (`avoid_vram_swap=True`), y usar `qwen3.5:4b` únicamente cuando la GPU está fría o en triaje dedicado.
- **Consecuencias:** Cero expulsiones no planificadas de VRAM, latencia TTFT en caliente de `~117 ms` y velocidad sostenida de `~40–42 tok/s` en generación de código verificada.
