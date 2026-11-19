---
name: db-safe-ops
description: Operaciones seguras para PostgreSQL, SQLite y Redis/Valkey con solo lectura por defecto, respaldos previos a migraciones, EXPLAIN y validación de integridad.
---

# Operaciones Seguras de Bases de Datos

## Reglas Obligatorias
1. **Solo lectura por defecto:** Usa `sqlite_ro` / `pg_ro` en `dbhub` o conexiones de solo lectura (`sqlite3 -readonly`, `psql` con usuario lector, `SCAN`/`GET`/`INFO` en Redis/Valkey).
2. **Respaldo previo obligatorio:** Antes de cualquier migración o escritura (`ALTER`, `UPDATE`, `DELETE`, `atlas migrate apply`), genera un respaldo con marca temporal:
   - SQLite: `sqlite3 db.sqlite ".backup 'db.sqlite.bak.$(date +%Y%m%d_%H%M%S)'"`
   - PostgreSQL: `pg_dump -Fc -h 127.0.0.1 -U oade_writer oade_dev > backup_$(date +%Y%m%d_%H%M%S).dump`
3. **Prohibido sin autorización explícita:** `DROP DATABASE`, `DROP TABLE`, `TRUNCATE`, `DELETE` sin `WHERE`, `FLUSHALL`, `FLUSHDB`.
4. **Optimización e Integridad:**
   - SQLite: `PRAGMA integrity_check;`, `EXPLAIN QUERY PLAN ...`
   - PostgreSQL: `EXPLAIN (ANALYZE, BUFFERS) ...` (solo en `SELECT` o dentro de transacción `BEGIN; ... ROLLBACK;` para escrituras).
   - Redis/Valkey: `valkey-cli PING`, `INFO memory`, `DBSIZE`, `SCAN 0 MATCH * COUNT 100` (nunca `KEYS *` en producción).
5. **Documentación de esquema:** Exporta DDL (`sqlite3 db ".schema"`, `pg_dump -s`, `atlas schema inspect`) y actualiza el documento de arquitectura de datos.
