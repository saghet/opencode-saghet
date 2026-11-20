# ADR-002: Supervisor Inteligente de Calidad e Integración con Gentle AI v4.5.0

- **Estado:** Aceptado y Verificado en Producción
- **Fecha:** 2026-11-20
- **Contexto:** En la versión inicial (`v0.1.0-alpha`), el flujo multiagente A–F dependía únicamente de instrucciones textuales en el prompt y marcaba un trabajo como exitoso si el proceso devolvía `returncode == 0`. Además, `gentle-ai 4.5.0` estaba instalado en el sistema pero desconectado del flujo de `saghet-orchestrator`.
- **Decisión:**
  1. Implementar `QualitySupervisor` ([scripts/supervisor/quality_supervisor.py](file:///home/saghet/Documents/OpenCode-Saghet/scripts/supervisor/quality_supervisor.py)) que prohíbe aceptar cualquier entrega sin evidencia verificable (`detect_missing_evidence`) o con contradicciones/bucles de razonamiento (`detect_reasoning_errors`).
  2. Integrar `Gentle AI v4.5.0` ([scripts/supervisor/gentle_ai_bridge.py](file:///home/saghet/Documents/OpenCode-Saghet/scripts/supervisor/gentle_ai_bridge.py)) con telemetría externa desactivada (`DO_NOT_TRACK=1`, `GENTLE_AI_TELEMETRY=0`) para clasificación de complejidad/riesgo, sincronización de `skill-registry` y soporte de revisión adversarial (`judgment-day` / Review Ledger 4R).
  3. Limitar los reintentos automáticos a un máximo de 2 correcciones guiadas (`max_iterations=3`) antes de emitir `REJECT` y ejecutar rollback automático del `git worktree` ([scripts/supervisor/worktree_manager.py](file:///home/saghet/Documents/OpenCode-Saghet/scripts/supervisor/worktree_manager.py)).
  4. Registrar todas las decisiones en `~/.local/share/opencode-saghet/supervisor_decisions.jsonl` (`chmod 600`).
- **Consecuencias:** Tasa de éxito verificada del `100 %` en los 10 benchmarks de inteligencia real, con recuperación automática comprobada en el escenario `10_fault_recovery`.
