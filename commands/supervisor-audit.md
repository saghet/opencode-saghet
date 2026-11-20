---
description: Run the Saghet Quality Supervisor & Independent Verification audit on current changes
agent: saghet-orchestrator
subtask: true
---

Ejecuta el flujo del Supervisor de Calidad (Fase E de validación independiente):
1. Clasifica el riesgo y verifica los diffs actuales (`git status`, `git diff`).
2. Delega en `code-reviewer` y `qa-engineer` (y `security-auditor` / `platform-security-engineer` si hay cambios de seguridad).
3. Emite veredicto (`ACCEPT`, `CORRECT` o `REJECT`) basado exclusivamente en evidencia verificable.
