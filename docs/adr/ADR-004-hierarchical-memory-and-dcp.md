# ADR-004: Memoria Jerárquica de 4 Niveles, Deduplicación y Protección de Contexto DCP

- **Estado:** Aceptado y Verificado en Producción
- **Fecha:** 2026-11-20
- **Contexto:** `opencode-mem@2.43.0` y `@tarquinen/opencode-dcp@3.2.1` proveen captura y poda de contexto, pero se detectaron tres limitaciones:
  1. `dcp.jsonc` tenía `"protectUserMessages": false`, podando instrucciones originales del usuario en sesiones largas.
  2. Faltaba una estructura jerárquica explícita (`session`, `project`, `experience`, `user`) con nivel de confianza, procedencia y aislamiento estricto entre proyectos.
  3. Existía riesgo de duplicar errores recurrentes o recuperar recuerdos irrelevantes en la ventana de 16k tokens.
- **Decisión:**
  1. Activar `"protectUserMessages": true` en `config/dcp.jsonc`.
  2. Implementar `HierarchicalMemoryStore` ([scripts/memory/hierarchical_memory.py](file:///home/saghet/Documents/OpenCode-Saghet/scripts/memory/hierarchical_memory.py)) sobre SQLite de la biblioteca estándar de Python (cero dependencias nuevas) en `~/.local/share/opencode-saghet/hierarchical_memory.db` (`0600`).
  3. Exigir en cada recuerdo: `provenance`, `created_at`/`updated_at`, `context` y `confidence` (`0.0–1.0`).
  4. Aplicar deduplicación por huella `SHA-256` normalizada + similitud de Jaccard (`>= 0.82`), incrementando `occurrence_count` en errores recurrentes y descartando recuerdos con `relevance_score < 0.14`.
- **Consecuencias:** Conocimiento verificado persistente entre sesiones, aislamiento garantizado entre proyectos y cero contaminación de contexto.
