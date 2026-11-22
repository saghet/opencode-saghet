# ADR-010: Semantic Project Transformation Engine y Visual Product Engineering

- **Estado:** Aceptado (`v0.5.0-gemini4-neon`)
- **Fecha:** 2026-11-22
- **Proyecto:** OpenCode-Saghet

## Problema
Los asistentes de código convencionales fallan al transformar herramientas CLI a aplicaciones Web o de Escritorio: suelen crear interfaces superficiales que envuelven o imprimen comandos de terminal, duplican lógica o entregan botones decorativos sin conexión real a las reglas de negocio.

## Alternativas Evaluadas
1. **Envolver el subproceso CLI detrás de un terminal web (`xterm.js` / `subprocess`):** Rechazada — confunde la interfaz original con la lógica funcional de la aplicación.
2. **Imponer una arquitectura pesada de 6 capas a scripts triviales:** Rechazada — genera sobreingeniería y dificulta mantenimiento.
3. **Motor de transformación semántica adaptativo (`SemanticTransformationEngine`) + especialista de producto visual (`VisualProductEngineer`) + validador anti-UI falsa + Matriz de Equivalencia Funcional ejecutable:** Seleccionada.

## Decisión
- Crear `scripts/intelligence/transformation_engine.py` capaz de:
  1. Analizar programas CLI (`argparse`, `click`, `typer`, `commander`, `sys.argv`), extraer comandos, parámetros, validaciones y lógica de dominio subyacente.
  2. Proponer una separación proporcional al tamaño del proyecto (`Domain`, `Application`, `Infrastructure`, `API`, `Presentation`, `Adapters`) manteniendo la CLI original operativa cuando es técnicamente viable.
  3. Generar aplicaciones Web (API REST real + frontend funcional conectado a endpoints reales) y aplicaciones de Escritorio (Tauri/Electron/PyQt6 según disponibilidad y objetivo) conectadas directamente al dominio extraído.
  4. Construir y ejecutar una **Matriz de Equivalencia Funcional** comparando salidas de la CLI original contra la nueva implementación.
- Crear `scripts/intelligence/visual_product.py` que selecciona una única combinación tecnológica coherente por proyecto, diseña la arquitectura UX/formularios/dashboards/accesibilidad y ejecuta `validate_ui_product_integrity()` para rechazar botones sin acción, datos falsos o páginas que impriman comandos de terminal.

## Consecuencias
- Ninguna transformación se marca exitosa por mera existencia visual: requiere ejecución real, pruebas de equivalencia y aprobación del `QualitySupervisor`.
