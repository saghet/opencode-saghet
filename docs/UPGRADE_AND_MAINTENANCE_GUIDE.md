# Guía de Actualización y Plan de Mantenimiento — OpenCode-Saghet

## 1. Guía de Actualización Segura (`update.sh`)

Para actualizar OpenCode-Saghet preservando tus configuraciones locales, bases de datos de memoria y snapshots:

```bash
cd ~/Documents/OpenCode-Saghet
./update.sh
```

### ¿Qué hace `update.sh`?
1. Valida la sintaxis e integridad de [compatibility.json](file:///home/saghet/Documents/OpenCode-Saghet/compatibility.json).
2. Verifica si existen cambios locales sin commit; si el árbol está limpio, ejecuta `git pull --ff-only`.
3. Invoca `./install.sh --skip-models`, lo cual:
   - Crea automáticamente un snapshot de respaldo en `~/.config/opencode/backups/install_<timestamp>/`.
   - Preserva `~/.config/opencode/dbhub.toml`, `~/.config/opencode/harness.json` y `~/.config/opencode/.saghet-dashboard-token`.
   - Actualiza plantillas, skills, comandos slash y temas.
   - Ejecuta `./doctor.sh` al finalizar.

---

## 2. Estrategia de Rollback y Restauración (`restore.sh`)

Si una actualización o cambio de configuración presenta algún problema, puedes listar y restaurar cualquier snapshot previo en segundos:

```bash
# 1. Listar respaldos disponibles
./restore.sh --list

# 2. Restaurar un snapshot específico (crea un respaldo pre_restore automático antes de restaurar)
./restore.sh <nombre_del_respaldo>

# 3. Reiniciar el servicio del Control Center
systemctl --user restart saghet-dashboard.service
```

---

## 3. Plan de Mantenimiento Periódico (Garuda / Arch Linux)

### 3.1 Mantenimiento Semanal
1. **Verificación de Salud y Pruebas de Aceptación:**
   ```bash
   ./doctor.sh
   python3 tests/run_acceptance.py
   ```
2. **Limpieza de Git Worktrees Temporales:**
   ```bash
   git worktree prune
   ```
3. **Revisión de Bitácora de Auditoría y Decisiones del Supervisor:**
   - Desde el módulo **8. Security Center** y **1. Agent Command Center** en `http://127.0.0.1:4780`, o inspeccionando:
     - `~/.local/share/opencode-saghet/audit.log`
     - `~/.local/share/opencode-saghet/supervisor_decisions.jsonl`
     - `~/.local/share/opencode-saghet/harness_traces.jsonl`

### 3.2 Mantenimiento Mensual (Actualizaciones de `pacman` y Modelos Ollama)
1. **Después de actualizar paquetes del sistema (`sudo pacman -Syu`):**
   - Si el paquete `opencode` o `opencode-desktop` se actualizó, re-aplica el wrapper visual sin tocar `app.asar`:
     ```bash
     ./scripts/build-desktop-matrix.sh
     ./doctor.sh
     ```
2. **Evaluación Antes de Cambiar o Actualizar Modelos en Ollama:**
   - **Regla obligatoria:** Nunca cambies el modelo titular en `opencode.json.tpl` sin ejecutar primero el Laboratorio de Evaluación y la batería de 10 benchmarks:
     ```bash
     python3 scripts/eval/model_lab.py --probe-model <nuevo_modelo>
     python3 tests/benchmarks/run_intelligence_benchmarks.py --model <nuevo_modelo>
     ```
3. **Integridad de Bases de Datos SQLite (Memoria Jerárquica y OpenCode DB):**
   ```bash
   sqlite3 -readonly ~/.local/share/opencode-saghet/hierarchical_memory.db "PRAGMA integrity_check;"
   sqlite3 -readonly ~/.local/share/opencode/opencode.db "PRAGMA integrity_check;"
   ```
4. **Rotación del Token de Seguridad del Control Center (Opcional):**
   ```bash
   rm -f ~/.config/opencode/.saghet-dashboard-token
   ./install.sh --skip-models
   systemctl --user restart saghet-dashboard.service
   ```
