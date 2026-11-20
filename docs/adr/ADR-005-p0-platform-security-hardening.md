# ADR-005: Blindaje de Seguridad P0 del Control Center y Guardrails de Secretos

- **Estado:** Aceptado y Verificado en Producción
- **Fecha:** 2026-11-20
- **Contexto:** La auditoría inicial de `dashboard/server.py` reveló ausencia de autenticación, vulnerabilidad a CSRF y DNS Rebinding, falta de validación de `agent`/`model`/`directory`, ausencia de control de procesos descendientes al cancelar trabajos y posibilidad de leer `.env*` desde comandos `bash` aunque estuvieran bloqueados en `read`/`edit`.
- **Decisión:**
  1. Generar y exigir un token criptográfico de 256 bits (`~/.config/opencode/.saghet-dashboard-token`, `chmod 600`) junto con cookie `HttpOnly; SameSite=Strict` y cabecera `X-Saghet-Token` / `X-CSRF-Token` en todas las mutaciones `POST /api/*`.
  2. Validar estrictamente `Host` (`127.0.0.1`, `localhost`, `[::1]`), `Origin`, `Referer` y `Sec-Fetch-Site` para bloquear DNS Rebinding y solicitudes cross-origin.
  3. Validar `agent` y `model` contra lista blanca (`is_valid_agent`, `is_valid_model`) y restringir `directory` (`validate_project_directory`) bloqueando `/etc`, `/root`, `/usr`, `/var`, `/proc` y directorios ocultos sensibles (`~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config`).
  4. Ejecutar subprocesos en su propio grupo de procesos (`start_new_session=True`) y terminar todo el árbol descendiente con `os.killpg` (`SIGTERM` → `SIGKILL`), limitando `MAX_CONCURRENT_JOBS=1`.
  5. Añadir reglas `deny` en `permission.bash` de `config/opencode.json.tpl` contra acceso a `.env*`, `.auth-token`, `.saghet-dashboard-token`, `service.json`, `*.key` y `*.pem`, y registrar todos los eventos en `~/.local/share/opencode-saghet/audit.log` (`0600`).
- **Consecuencias:** Plataforma local-first blindada frente a vectores web locales (CSRF/DNS Rebinding), fugas de secretos y procesos huérfanos, sin perder capacidades legítimas de automatización.
