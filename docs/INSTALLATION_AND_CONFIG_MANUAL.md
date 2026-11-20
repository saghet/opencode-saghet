# Manual de Instalación y Configuración — OpenCode-Saghet (Garuda / Arch Linux)

## 1. Requisitos del Sistema

- **Sistema Operativo:** Garuda Linux o Arch Linux (`x86_64`).
- **Hardware Objetivo:**
  - CPU: AMD Ryzen 9 7940HS (o equivalente multi-núcleo).
  - GPU: NVIDIA GeForce RTX 4060 Laptop (`8188 MiB VRAM`, driver NVIDIA con soporte CUDA).
  - RAM: `32 GiB`.
  - Espacio libre en disco: `>= 25 GiB` para modelos locales de Ollama.
- **Dependencias Base:** `git`, `nodejs`, `npm`, `python3`, `sqlite`, `opencode` (`v2.3.2`), `ollama` (`0.40.16`), `gentle-ai` (`v4.5.0`).

---

## 2. Instalación Paso a Paso

### 2.1 Instalación Estándar (Idempotente)

```bash
git clone https://github.com/saghet/opencode-saghet.git
cd opencode-saghet
./install.sh
```

El instalador realiza automáticamente los siguientes 8 pasos:
1. Detecta la distribución Linux (`/etc/os-release`).
2. Verifica e instala paquetes faltantes mediante `pacman -S --needed`.
3. Comprueba el estado de la GPU NVIDIA y CUDA (`nvidia-smi`).
4. Crea una copia de seguridad completa en `~/.config/opencode/backups/install_<timestamp>/`.
5. Despliega configuraciones (`opencode.json` con permisos `0600`, `dcp.jsonc`, `opencode-mem.jsonc`, `harness.json`, `tui.json`, `AGENTS.md`), genera el token de seguridad `~/.config/opencode/.saghet-dashboard-token` (`0600`), instala comandos slash (`commands/*.md`), skills (`skills/*`), temas, wrapper de escritorio y habilita el servicio `systemd --user` (`saghet-dashboard.service`).
6. Verifica y descarga los modelos base en Ollama (`qwen3.5:9b`, `qwen3.5:4b`, `qwen2.5-coder:7b`, `abliterant/qwen3.5-rana:9b`) si hay más de 20 GiB libres (o usa `./install.sh --skip-models` para omitir descargas).
7. Recarga la configuración de OpenCode (`opencode reload`) y sincroniza el registro de skills con `gentle-ai skill-registry refresh`.
8. Ejecuta `./doctor.sh` para certificar que todos los subsistemas estén en estado `SALUDABLE`.

### 2.2 Configuración del Servicio Ollama para 8 GB VRAM

Para aplicar o verificar el override de `systemd` sobre el servicio del sistema `ollama.service`:

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo cp config/ollama-override.conf /etc/systemd/system/ollama.service.d/override.conf
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Parámetros aplicados en [config/ollama-override.conf](file:///home/saghet/Documents/OpenCode-Saghet/config/ollama-override.conf):
- `OLLAMA_FLASH_ATTENTION=1`
- `OLLAMA_KV_CACHE_TYPE=q8_0`
- `OLLAMA_MAX_LOADED_MODELS=1`
- `OLLAMA_NUM_PARALLEL=1`
- `OLLAMA_CONTEXT_LENGTH=16384`
- `OLLAMA_KEEP_ALIVE=30m`
- `OLLAMA_LOAD_TIMEOUT=15m`

---

## 3. Manual de Configuración por Subsistema

| Archivo en Repo | Destino Desplegado | Propósito y Parámetros Clave |
| :--- | :--- | :--- |
| [config/opencode.json.tpl](file:///home/saghet/Documents/OpenCode-Saghet/config/opencode.json.tpl) | `~/.config/opencode/opencode.json` (`0600`) | Define los **17 especialistas**, proveedor Ollama (`chunkTimeout: 900000`), servidores MCP (`dbhub`, `sequential-thinking`, `context7`), plugins y matriz de permisos `permission` (`bash`, `read`, `edit`). |
| [config/dcp.jsonc](file:///home/saghet/Documents/OpenCode-Saghet/config/dcp.jsonc) | `~/.config/opencode/dcp.jsonc` | Dynamic Context Pruning (`minContextLimit: 4500`, `maxContextLimit: 11500`, `protectUserMessages: true`, `deduplication: true`, `purgeErrors: true`). |
| [config/opencode-mem.jsonc](file:///home/saghet/Documents/OpenCode-Saghet/config/opencode-mem.jsonc) | `~/.config/opencode/opencode-mem.jsonc` | Memoria vectorial (`opencodeModel: "qwen3.5:9b"` alineado con el modelo principal para evitar thrashing de VRAM; UI en `127.0.0.1:4747`). |
| [config/harness.json](file:///home/saghet/Documents/OpenCode-Saghet/config/harness.json) | `~/.config/opencode/harness.json` | Adaptador ACP DeepSeek Harness (`enabled: true/false`, `cordis_in_core: false`, `serialize_local_gpu_nodes: true`). |
| [config/dbhub.toml.tpl](file:///home/saghet/Documents/OpenCode-Saghet/config/dbhub.toml.tpl) | `~/.config/opencode/dbhub.toml` | Conexiones SQLite (`sqlite_ro`, `sqlite_rw`) y PostgreSQL (`pg_ro`, `pg_rw`) con variables de entorno `${OADE_PG_READER_PASS}` / `${OADE_PG_WRITER_PASS}`. |
| [config/saghet-dashboard.service.tpl](file:///home/saghet/Documents/OpenCode-Saghet/config/saghet-dashboard.service.tpl) | `~/.config/systemd/user/saghet-dashboard.service` | Servicio en segundo plano del Saghet Matrix Control Center en `http://127.0.0.1:4780`. |

---

## 4. Uso Diario y Comandos Principales

- **Abrir Saghet Matrix Control Center (10 Módulos Web):**
  ```bash
  opencode-saghet --dashboard
  # o abrir http://127.0.0.1:4780 en el navegador local
  ```
- **Iniciar OpenCode Desktop con Overlay Matrix Protocol:**
  ```bash
  opencode-saghet --desktop
  ```
- **Usar OpenCode TUI / CLI con `saghet-orchestrator`:**
  ```bash
  opencode-saghet
  ```
- **Ejecutar Diagnóstico Integral:**
  ```bash
  ./doctor.sh
  ```
