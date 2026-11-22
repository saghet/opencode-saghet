# ADR-009: Semantic Project Understanding Engine y GitHub Reuse Intelligence

- **Estado:** Aceptado (`v0.5.0-gemini4-neon`)
- **Fecha:** 2026-11-22
- **Proyecto:** OpenCode-Saghet

## Problema
Para comprender repositorios desconocidos y reutilizar soluciones de GitHub de forma segura, los agentes necesitan: (1) un grafo semántico completo del proyecto (módulos, funciones, clases, servicios, flujos, contratos e impacto previo a cambios) con caché incremental, y (2) un motor que busque, inspeccione estáticamente, valide licencias SPDX y recomiende reutilizar, adaptar o construir desde cero sin ejecutar código externo no confiable.

## Alternativas Evaluadas
1. **Reemplazar `ProjectIntelligenceEngine` por un servidor externo pesado (ej. Neo4j + servicios Docker):** Rechazada — duplica almacenamiento, consume RAM/VRAM innecesariamente y rompe la portabilidad en Garuda/Arch Linux.
2. **Exigir `tree-sitter` binario obligatorio:** Rechazada — en Python 3.14 del sistema `tree_sitter` no está preinstalado; exigir compilación nativa rompería la instalación limpia.
3. **Extender `ProjectIntelligenceEngine` con `SemanticProjectEngine` (adaptador Tree-sitter opcional + AST Python + analizadores estructurales multilenguaje) y añadir `GitHubReuseEngine` con análisis puramente estático y matriz SPDX:** Seleccionada.

## Decisión
- Crear `scripts/intelligence/semantic_engine.py` reutilizando la caché incremental SQLite (`mtime_ns` + `sha256`) y FTS5 de `ProjectIntelligenceEngine`, añadiendo detección de lenguajes/frameworks, clasificación de capas (dominio, aplicación, infraestructura, API, CLI, presentación), contratos de interfaces públicas, grafo completo tipado (`RepositoryGraph`) y recuperación de `ContextIntelligence` antes de modificar código.
- Crear `scripts/intelligence/github_reuse.py` integrando `gh` CLI / GitHub REST API (y soporte de referencias Context7), inspección estática en directorio temporal aislado (sin ejecutar scripts, `setup.py`, `postinstall` ni hooks git), escáner de seguridad y prompt-injection, detector de licencias SPDX con matriz de compatibilidad e informe estructurado de reutilización (`reuse | adapt | build_from_scratch`).

## Consecuencias
- Reutiliza el índice incremental existente (< 50 ms en caché caliente) y añade soporte Tree-sitter automático si el usuario instala `tree-sitter` en su entorno.
- Garantiza cumplimiento legal de licencias y aislamiento de seguridad frente a código externo.
