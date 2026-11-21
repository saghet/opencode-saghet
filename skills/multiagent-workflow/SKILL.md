---
name: multiagent-workflow
description: Protocolo de orquestación multiagente secuencial (Fases A-F) con Supervisor de Calidad, Gentle AI y límite de 8 GB VRAM.
---

# Flujo Multiagente con Supervisor de Calidad (OpenCode-Saghet)

1. **FASE A — Comprensión y Clasificación Gentle AI:** Analiza el objetivo, clasifica complejidad (`low`, `medium`, `high`, `critical`) y riesgo (`read_only`, `standard_mutation`, `architectural`, `security_sensitive`), y selecciona el especialista y modelo respetando `OLLAMA_MAX_LOADED_MODELS=1`. Si involucra un repositorio remoto, clónalo con `bash` (`git clone`) y verifica su ruta real con `ls` ANTES de delegar en cualquier subagente.
2. **FASE B — Investigación Secuencial y Acotada (Anti-Amnesia):** Explora el repositorio con lecturas acotadas (`fast-helper`, `researcher`, `architect`, `integration-architect`). Lanza **1 solo subagente a la vez**, inicia el prompt con `OBJETIVO INMUTABLE: ...` y exige respuesta en `<= 5` llamadas de herramientas sin consultar JSONs masivos de `api.github.com` por `webfetch`.
3. **FASE C — Planificación y DAG:** Divide el trabajo en subtareas con dependencias explícitas y criterios de aceptación objetivos. Si solo se pidió análisis, presenta el plan, pregunta confirmación para Fase 1 y detente.
4. **FASE D — Implementación Aislada:** Delega secuencialmente en especialistas (`senior-developer`, `frontend-specialist`, `backend-specialist`, `database-specialist`, `devops-engineer`, `performance-engineer`, `documentation-engineer`). Usa `worktree-isolation` para cambios de riesgo medio/alto.
5. **FASE E — Supervisión de Calidad y Validación Independiente:**
   - Prohibido aceptar una tarea solo porque el agente terminó su respuesta.
   - Exige evidencia real: diffs verificados, pruebas ejecutadas por `qa-engineer` con código de salida `0`, revisión por `code-reviewer` y auditoría en `security-auditor` / `platform-security-engineer`.
   - Detecta errores de razonamiento, contradicciones o falta de evidencia. Aplica máximo 2 reintentos controlados (`CORRECT`) antes de hacer rollback (`REJECT`).
6. **FASE F — Entrega Ejecutiva y Pausa:** Presenta Resumen Ejecutivo, Evidencia Real (archivos, líneas, tests) y propone la siguiente fase deteniendo el turno sin llamar herramientas.
