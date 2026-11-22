# ADR-008: Gemini 4 Neon Intelligence Core y Coordinación Híbrida

- **Estado:** Aceptado (`v0.5.0-gemini4-neon`)
- **Fecha:** 2026-11-22
- **Proyecto:** OpenCode-Saghet

## Problema
OpenCode-Saghet (`v0.4.0`) ejecuta todos los roles exclusivamente sobre modelos Ollama locales de 4B–9B (RTX 4060 8 GB VRAM, ventana efectiva 22.5k tokens). Para comprensión arquitectónica multi-repositorio, planificación compleja, transformación semántica entre plataformas e investigación de reutilización, se requiere un coordinador de razonamiento profundo y contexto largo sin perder compatibilidad con OpenCode, Gentle AI ni Ollama local.

## Alternativas Evaluadas
1. **Reemplazar OpenCode y Ollama por un agente exclusivo de Gemini:** Rechazada — rompe el núcleo de ejecución, el modo offline/local-first en Garuda Linux y las políticas de permisos/worktrees de OpenCode.
2. **Usar endpoints no oficiales o inventar identificadores de modelo:** Rechazada — viola trazabilidad y estabilidad.
3. **Integración híbrida mediante proveedor oficial Google Gemini API (`gemini-4-neon`) en OpenCode + coordinador `Gemini4NeonCoordinator` con fallback transparente a Ollama:** Seleccionada.

## Decisión
- Configurar el proveedor oficial `google` (`@ai-sdk/google`) en `config/opencode.json.tpl` con el identificador verificado `gemini-4-neon` (contexto unificado 1,048,576 tokens, salida hasta 65,536 tokens, `thinkingLevel` configurable) junto a los modelos Ollama existentes.
- Implementar `scripts/intelligence/gemini_core.py` con:
  - Cliente oficial REST contra `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` y verificación de disponibilidad vía `GET /v1beta/models`.
  - Gestión de límites, reintentos exponenciales (HTTP 429/500/503), cuota de solicitudes/tokens y conmutación dinámica de modelo sin alterar el núcleo.
  - Recuperación selectiva de contexto acotado (integrada con `SemanticProjectEngine` y `HierarchicalMemoryStore`), prohibiendo el volcado indiscriminado de repositorios completos.
  - `FileOwnershipCoordinator` para impedir que especialistas ejecuten ediciones contradictorias sobre los mismos archivos.
  - Registro auditable de decisiones, herramientas utilizadas y resultados (`~/.local/share/opencode-saghet/gemini_decisions.jsonl`, permisos `0600`).
  - Fallback automático y explícito a `SmartModelRouter` / Ollama local cuando no exista `GEMINI_API_KEY` o se agote la cuota.

## Consecuencias
- Permite activar Gemini 4 Neon inmediatamente con `GEMINI_API_KEY` o `opencode auth login` sin romper instalaciones offline.
- Preserva `OLLAMA_MAX_LOADED_MODELS=1` y el presupuesto de 8 GB VRAM para ejecutores locales.
- Todas las decisiones del coordinador quedan auditables y verificables.
