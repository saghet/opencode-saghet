# ADR-007: Cognitive Evolution Engine V3

- **Estado:** Aceptado e Implementado (`v0.4.0-cognitive-evolution-v3`)
- **Contexto:** Tras `v0.3.0-cognitive-v2`, la auditoría del código reveló que `CognitiveBridge` solo se invocaba manualmente (`/cognitive-context`), `ProjectIntelligenceEngine` no respetaba `.gitignore` ni usaba su índice FTS5 ni construía un Repo Map estructural, `HierarchicalMemoryStore` no resolvía contradicciones en memoria de proyecto, `SmartModelRouter` no consumía estadísticas históricas de `OutcomeLearningEngine` y no existía un registro formal de experimentos para mejora continua.

## Decisiones Arquitectónicas
1. **Repo Intelligence sin dependencias pesadas obligatorias:** Se amplía `ProjectIntelligenceEngine` con parser `.gitignore`/`.saghetignore`, caché `sha256` por contenido, extracción multilenguaje (Python AST + analizadores estructurales JS/TS/Rust/Go/Bash), PageRank para `build_repo_map()`, detección de ciclos y duplicados, y búsqueda híbrida FTS5+símbolos (`select_relevant_context`), evitando requerir Tree-sitter nativo o servicios externos permanentes en 8 GB VRAM.
2. **Resolución de contradicciones y blindaje de memoria:** `HierarchicalMemoryStore` distingue polaridad afirmativa/negativa antes de deduplicar, marca automáticamente recuerdos previos contradictorios como `superseded`, rechaza *prompt injection* y expira recuerdos temporales mediante `prune_expired_memories()`.
3. **Integración viva sin duplicar coordinadores:** `CognitiveBridge` se conecta directamente a `HarnessWorkflowEngine` y `QualitySupervisor` (preservando ACP, Task Board y Execution Traces), evitando crear un segundo orquestador.
4. **Enrutamiento empírico con política estricta de VRAM:** `SmartModelRouter` añade especialidades `research`, `debugging` y `memory` e incorpora un ajuste acotado `[-5, +5]` basado en `outcome_records` (`samples >= 3`), manteniendo `OLLAMA_MAX_LOADED_MODELS=1` e histéresis anti-swap en RTX 4060 8 GB.
5. **Continuous Improvement Engine con puerta de seguridad:** `ExperimentRegistry` registra hipótesis, métricas antes/después y pruebas controladas, bloqueando cualquier mutación autónoma sobre políticas de seguridad, permisos o núcleo de OpenCode.

## Evidencia
- `python3 -m unittest discover -s tests -p "test_phase*.py" -v` -> `35/35 OK`.
- `python3 tests/benchmarks/run_cognitive_benchmarks.py` -> `20/20 (100.0 %)`.
