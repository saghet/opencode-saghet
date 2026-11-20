# Informe de Seguridad P0 y Resultados de Benchmarks — OpenCode-Saghet

## 1. Informe de Auditoría y Remediación de Seguridad (Fase 7 / P0)

| Vector Auditado | Estado Inicial (`v0.1.0-alpha`) | Control Implementado (`v0.2.0-matrix-nextgen`) | Evidencia en Código | Estado |
| :--- | :--- | :--- | :--- | :---: |
| **Autenticación y Autorización** | Sin autenticación en `:4780` | Token de 256 bits en `~/.config/opencode/.saghet-dashboard-token` (`0600`), validación con `hmac.compare_digest` en `X-Saghet-Token`, `Authorization: Bearer` o cookie `HttpOnly; SameSite=Strict` + `X-CSRF-Token`. | [dashboard/server.py](file:///home/saghet/Documents/OpenCode-Saghet/dashboard/server.py#L90-L115), [L760-L785](file:///home/saghet/Documents/OpenCode-Saghet/dashboard/server.py#L760-L785) | **CERRADO (Verificado en `test_g`)** |
| **CSRF y Validación de Origin / Referer** | Sin validación de `Origin` ni `Sec-Fetch-Site` | Bloqueo con `HTTP 403` ante `Sec-Fetch-Site: cross-site`, `Origin: null` o cualquier `Origin`/`Referer` cuyo hostname no sea `127.0.0.1`, `localhost` o `[::1]`. | [dashboard/server.py](file:///home/saghet/Documents/OpenCode-Saghet/dashboard/server.py#L720-L759) | **CERRADO (Verificado en `test_g`)** |
| **DNS Rebinding (Validación de Host)** | Cualquier cabecera `Host` era aceptada | Validación estricta de `Host` contra `ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}` tanto en `GET` como en `POST`. | [dashboard/server.py](file:///home/saghet/Documents/OpenCode-Saghet/dashboard/server.py#L43), [L720-L731](file:///home/saghet/Documents/OpenCode-Saghet/dashboard/server.py#L720-L731) | **CERRADO (Verificado en `test_g`)** |
| **Restricción de Directorios** | Permitía cualquier directorio existente o crear carpetas arbitrarias | `validate_project_directory()` bloquea `/`, `$HOME` raíz, prefijos del sistema (`/etc`, `/root`, `/usr`, `/var`, `/boot`, `/proc`, `/sys`, `/dev`) y directorios ocultos sensibles (`~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config`, `~/.local`, `~/.opencode-mem`). | [dashboard/server.py](file:///home/saghet/Documents/OpenCode-Saghet/dashboard/server.py#L44-L72), [L391-L438](file:///home/saghet/Documents/OpenCode-Saghet/dashboard/server.py#L391-L438) | **CERRADO (Verificado en `test_g`)** |
| **Validación de Agentes y Modelos** | Interpolación directa en CLI sin lista blanca | `is_valid_agent()` verifica contra los 17 agentes de `opencode.json`; `is_valid_model()` rechaza flags (`-...`), valida regex estricta y comprueba contra `opencode.json` y modelos de Ollama. | [dashboard/server.py](file:///home/saghet/Documents/OpenCode-Saghet/dashboard/server.py#L367-L388) | **CERRADO (Verificado en `test_g`)** |
| **Ejecución Automática (`--auto`) y Operaciones Destructivas** | `--auto` sin inspección de prompt | Filtro previo contra acceso a secretos (`_SECRET_ACCESS_RE`) y bloqueo de patrones destructivos (`DROP DATABASE/TABLE`, `TRUNCATE`, `rm -rf /`, `git push --force`) sin `approve_destructive: true`. | [dashboard/server.py](file:///home/saghet/Documents/OpenCode-Saghet/dashboard/server.py#L79-L87), [L1028-L1055](file:///home/saghet/Documents/OpenCode-Saghet/dashboard/server.py#L1028-L1055) | **CERRADO (Verificado en `test_g`)** |
| **Protección de Procesos Descendientes y Límites de Jobs** | `proc.terminate()` dejaba hijos huérfanos; `_JOBS` sin límite | Subprocesos lanzados con `start_new_session=True`; `_terminate_process_tree()` envía `SIGTERM` → `SIGKILL` a todo el grupo (`os.killpg`); límite `MAX_CONCURRENT_JOBS=1` (`HTTP 429`) y purga automática `MAX_STORED_JOBS=50`. | [dashboard/server.py](file:///home/saghet/Documents/OpenCode-Saghet/dashboard/server.py#L180-L218) | **CERRADO (Verificado)** |
| **Protección de Secretos en Shell y Logs** | `permission.bash` permitía `cat .env` | Reglas `deny` añadidas en `permission.bash`, `permission.read` y `permission.edit` para `.env*`, `.auth-token`, `.saghet-dashboard-token`, `service.json`, `*.key`, `*.pem` y `.ssh/id_*`, más `_redact_secrets()` en salidas de servidor. | [config/opencode.json.tpl](file:///home/saghet/Documents/OpenCode-Saghet/config/opencode.json.tpl#L187-L206), [dashboard/server.py](file:///home/saghet/Documents/OpenCode-Saghet/dashboard/server.py#L148-L154) | **CERRADO (Verificado en `test_e`, `test_g`)** |
| **Registro de Auditoría** | Inexistente | Bitácora JSONL append-only en `~/.local/share/opencode-saghet/audit.log` (`0600`) y visualización en el módulo **8. Security Center**. | [dashboard/server.py](file:///home/saghet/Documents/OpenCode-Saghet/dashboard/server.py#L113-L145) | **CERRADO (Verificado en `test_g`)** |

---

## 2. Resultados del Laboratorio de Evaluación de Modelos (RTX 4060 — 8188 MiB VRAM)

Fuente verificada: [benchmarks/model_evaluation_matrix.json](file:///home/saghet/Documents/OpenCode-Saghet/benchmarks/model_evaluation_matrix.json)

| Modelo Local | Parámetros | Quant | Tools | `tok/s` | `TTFT (ms)` | VRAM Pico (`MiB`) | Score Classification | Score Coding | Score Architecture | Score Indep. Review | Score Security Audit | Rol Asignado por `SmartModelRouter` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `qwen3.5:9b` | `9.2B` | `Q4_K_M` | Sí | **`42.32`** | `117.6` | `6564.0` | `82.70` | **`95.10`** | **`93.95`** | **`95.40`** | `94.55` | **Titular Coding, Arquitectura, Orquestación y Memoria** |
| `qwen3.5:4b` | `4.3B` | `Q4_K_M` | Sí | **`69.30`** | `95.4` | `4078.0` | **`91.55`** | `86.26` | `79.40` | `80.58` | `81.08` | **Titular Clasificación Rápida (`fast-helper`)** |
| `abliterant/qwen3.5-rana:9b` | `9.2B` | `Q4_K_M` | Sí | `42.12` | `135.0` | `6560.0` | `81.47` | `91.90` | `93.45` | `94.85` | **`94.75`** | **Titular Auditoría de Seguridad y Revisión Independiente** |
| `qwen3:8b` | `8.2B` | `Q4_K_M` | Sí | `46.80` | `122.0` | `5420.0` | `82.43` | `87.34` | `88.47` | `87.40` | `88.05` | **Fallback Principal** |
| `qwen2.5-coder:7b` | `7.6B` | `Q4_K_M` | No | `51.15` | `108.0` | `5106.0` | `53.21` | `68.70` | `82.03` | `78.20` | `72.30` | Penalizado en agentes por `tools: false` |
| `qwen3-coder:30b` | `30.5B` | `Q4_K_M` | Sí | `9.40` | `4850.0` | `7980.0` (+RAM) | `52.20` | `86.94` | `90.52` | `93.90` | `94.70` | Penalizado por exceder presupuesto seguro de 8 GB VRAM |

---

## 3. Resultados de los 10 Benchmarks Reproducibles de Inteligencia Real

Fuente verificada: [benchmarks/saghet_intelligence_benchmarks.json](file:///home/saghet/Documents/OpenCode-Saghet/benchmarks/saghet_intelligence_benchmarks.json)
Ejecutado mediante `python3 tests/benchmarks/run_intelligence_benchmarks.py` en proyectos Git aislados con `artificial_test_mutations_allowed: false`:

- **Total de escenarios ejecutados:** `10`
- **Escenarios superados en primera ejecución completa:** **`10 / 10` (`100.0 %`)**
- **Tiempo total de ejecución:** `33.15 s`
- **Uso pico de VRAM observado (`nvidia-smi`):** **`6568.0 MiB` / `8188.0 MiB`** (`80.2 %`, sin desbordamiento)
- **Uso pico de RAM del sistema:** `9153.9 MiB` / `31295.2 MiB` (`29.2 %`)
- **Latencia del endpoint `/api/telemetry`:** Reducida de `627.3 ms` a **`38.4 ms`** (`16.3x` de mejora tras lectura directa SQLite RO).
