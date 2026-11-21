#!/usr/bin/env python3
"""
Memoria Jerárquica y Conocimiento Verificado — OpenCode-Saghet (Fase 4).

Evalúa e integra `opencode-mem` y `DCP` sin añadir dependencias externas.
Niveles de memoria:
1. session: Memoria de sesión activa.
2. project: Memoria por proyecto (arquitectura, ADRs, convenciones del repositorio).
3. experience: Memoria de experiencias (ejecuciones verificadas, errores recurrentes, soluciones comprobadas).
4. user: Memoria de usuario (perfil, hardware RTX 4060 8 GB, Garuda Linux, preferencias).

Cada recuerdo incluye obligatoriamente:
- provenance (procedencia)
- created_at / updated_at (fecha ISO 8601 + epoch_ms)
- context (proyecto, sesión, agente, categoría, evidencia, etiquetas)
- confidence (nivel de confianza 0.0 a 1.0)

Incluye deduplicación semántica/léxica por huella y similitud Jaccard, y filtrado estricto
de relevancia para no contaminar la ventana de 16k tokens con recuerdos irrelevantes.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import urllib.request
import uuid
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent.parent
OPENCODE_CONFIG_DIR = Path.home() / ".config" / "opencode"
OPENCODE_MEM_DATA_DIR = Path.home() / ".opencode-mem" / "data"
SAGHET_STATE_DIR = Path.home() / ".local" / "share" / "opencode-saghet"
DEFAULT_MEMORY_DB_PATH = SAGHET_STATE_DIR / "hierarchical_memory.db"

VALID_TIERS = ("session", "project", "experience", "user")
VALID_CATEGORIES = (
    "verified_execution",
    "recurring_error",
    "architectural_decision",
    "proven_solution",
    "session_context",
    "user_preference",
    "user_correction",
    "rejected_solution",
    "accepted_solution",
    "consolidated_procedure",
)
VALID_STATUSES = ("valid", "provisional", "superseded", "invalidated")

_SENSITIVE_SECRET_RE = re.compile(
    r"(?i)("
    r"sk-[a-z0-9]{16,}|"
    r"ghp_[a-z0-9]{20,}|"
    r"AIza[0-9A-Za-z\-_]{20,}|"
    r"-----BEGIN\s+(?:RSA|OPENSSH|EC|PGP)?\s*PRIVATE KEY-----|"
    r"(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|contraseña)\s*[:=]\s*['\"]?[^\s'\"]{6,}"
    r")"
)


def contains_sensitive_secret(text: str) -> bool:
    """Detecta credenciales, tokens o secretos para evitar almacenarlos en memoria."""
    return bool(_SENSITIVE_SECRET_RE.search(text or ""))

_STOPWORDS = {
    "de",
    "la",
    "el",
    "en",
    "y",
    "a",
    "los",
    "del",
    "se",
    "las",
    "por",
    "un",
    "para",
    "con",
    "no",
    "una",
    "su",
    "al",
    "es",
    "lo",
    "como",
    "mas",
    "pero",
    "sus",
    "le",
    "ya",
    "o",
    "the",
    "and",
    "to",
    "of",
    "in",
    "for",
    "on",
    "with",
    "is",
    "that",
    "by",
    "at",
    "from",
}
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_./:-]{2,}")


def tokenize_meaningful(text: str) -> set[str]:
    tokens = {m.group(0).lower().strip(".,;:/") for m in _TOKEN_RE.finditer(text or "")}
    return {t for t in tokens if t not in _STOPWORDS and len(t) >= 2}


def compute_content_fingerprint(tier: str, category: str, project_path: str, content: str) -> str:
    norm_tokens = sorted(tokenize_meaningful(content))
    payload = f"{tier}|{category}|{project_path}|{' '.join(norm_tokens)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def jaccard_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    inter = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return inter / union if union > 0 else 0.0


_SEMANTIC_CONCEPT_GROUPS: tuple[set[str], ...] = (
    {"auth", "authentication", "autenticacion", "login", "jwt", "token", "oauth", "sesion", "session"},
    {"db", "database", "sql", "sqlite", "postgres", "postgresql", "redis", "migracion", "migration", "schema", "esquema"},
    {"perf", "performance", "rendimiento", "latencia", "latency", "velocidad", "speed", "vram", "cuda", "cache"},
    {"bug", "error", "fallo", "failure", "crash", "traceback", "exception", "excepcion", "debug", "depuracion"},
    {"arch", "architecture", "arquitectura", "design", "diseno", "contrato", "contract", "modular", "dag"},
    {"test", "tests", "unittest", "pytest", "prueba", "pruebas", "qa", "regresion", "regression"},
    {"sec", "security", "seguridad", "xss", "csrf", "injection", "secreto", "secret", "permiso", "permission"},
    {"simple", "simplicity", "simplicidad", "eficiente", "efficient", "minimal", "conciso", "concise"},
)


def expand_semantic_tokens(tokens: set[str]) -> set[str]:
    """Expande tokens con conceptos equivalentes bilingües (ES/EN) para recuperación híbrida."""
    expanded = set(tokens)
    for tok in tokens:
        for group in _SEMANTIC_CONCEPT_GROUPS:
            if tok in group:
                expanded.update(group)
    return expanded


def compute_local_ngram_embedding(text: str, dims: int = 128) -> list[float]:
    """
    Embedding semántico local determinista (sin dependencias externas):
    combina n-gramas de caracteres y tokens expandidos en un vector L2-normalizado.
    """
    vec = [0.0] * dims
    clean = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if not clean:
        return vec

    tokens = expand_semantic_tokens(tokenize_meaningful(clean))
    for tok in tokens:
        h = int.from_bytes(hashlib.blake2b(tok.encode("utf-8"), digest_size=4).digest(), "little")
        vec[h % dims] += 1.5

    padded = f" {clean} "
    for i in range(max(0, len(padded) - 2)):
        tri = padded[i : i + 3]
        h = int.from_bytes(hashlib.blake2b(tri.encode("utf-8"), digest_size=4).digest(), "little")
        vec[h % dims] += 0.5

    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0.0:
        vec = [round(v / norm, 5) for v in vec]
    return vec


def compute_embedding(text: str, use_ollama: bool = False, model: str = "nomic-embed-text") -> list[float]:
    """Calcula embedding local; usa Ollama `/api/embed` solo si `use_ollama=True` y está disponible."""
    if use_ollama:
        try:
            payload = json.dumps({"model": model, "input": (text or "")[:1500]}).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/embed",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            embs = data.get("embeddings") or []
            if embs and isinstance(embs[0], list):
                return [float(x) for x in embs[0]]
        except Exception:
            pass
    return compute_local_ngram_embedding(text)


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    na = math.sqrt(sum(a * a for a in vec_a))
    nb = math.sqrt(sum(b * b for b in vec_b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def inspect_opencode_mem_and_dcp() -> dict:
    """Inspecciona el estado real de opencode-mem y DCP antes de operar."""
    dcp_path = OPENCODE_CONFIG_DIR / "dcp.jsonc"
    mem_cfg_path = OPENCODE_CONFIG_DIR / "opencode-mem.jsonc"
    if not dcp_path.is_file():
        dcp_path = REPO_DIR / "config" / "dcp.jsonc"
    if not mem_cfg_path.is_file():
        mem_cfg_path = REPO_DIR / "config" / "opencode-mem.jsonc"

    dcp_cfg = {}
    mem_cfg = {}
    try:
        if dcp_path.is_file():
            dcp_cfg = json.loads(dcp_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        if mem_cfg_path.is_file():
            mem_cfg = json.loads(mem_cfg_path.read_text(encoding="utf-8"))
    except Exception:
        pass

    db_files = []
    if OPENCODE_MEM_DATA_DIR.is_dir():
        for entry in sorted(OPENCODE_MEM_DATA_DIR.glob("*.db")):
            db_files.append({"name": entry.name, "size_bytes": entry.stat().st_size})

    return {
        "opencode_mem": {
            "configured": bool(mem_cfg),
            "model": mem_cfg.get("opencodeModel"),
            "embedding_model": mem_cfg.get("embeddingModel"),
            "max_memories_per_chat": (mem_cfg.get("chatMessage") or {}).get("maxMemories", 6),
            "web_port": mem_cfg.get("webServerPort", 4747),
            "data_dir_exists": OPENCODE_MEM_DATA_DIR.is_dir(),
            "databases": db_files,
        },
        "dcp": {
            "enabled": bool(dcp_cfg.get("enabled", True)),
            "protect_user_messages": bool((dcp_cfg.get("compress") or {}).get("protectUserMessages", False)),
            "min_context_limit": (dcp_cfg.get("compress") or {}).get("minContextLimit"),
            "max_context_limit": (dcp_cfg.get("compress") or {}).get("maxContextLimit"),
            "deduplication": bool(((dcp_cfg.get("strategies") or {}).get("deduplication") or {}).get("enabled", True)),
            "purge_errors": bool(((dcp_cfg.get("strategies") or {}).get("purgeErrors") or {}).get("enabled", True)),
        },
    }


class HierarchicalMemoryStore:
    """
    Almacén de Memoria Jerárquica (session, project, experience, user) sobre SQLite local.
    Garantiza procedencia, fecha, contexto, nivel de confianza, deduplicación y recuperación relevante.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or DEFAULT_MEMORY_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return contextlib.closing(conn)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    tier TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    project_path TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    fingerprint TEXT NOT NULL,
                    occurrence_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    epoch_ms INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'valid',
                    valid_until TEXT DEFAULT NULL,
                    importance REAL NOT NULL DEFAULT 0.5,
                    preference_source TEXT DEFAULT NULL,
                    preference_scope TEXT DEFAULT NULL,
                    preference_key TEXT DEFAULT NULL,
                    superseded_by TEXT DEFAULT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    relations_json TEXT NOT NULL DEFAULT '[]',
                    embedding_json TEXT DEFAULT NULL
                )
                """
            )
            self._migrate_schema(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_tier ON memories(tier)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_path)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_fingerprint ON memories(fingerprint)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_pref_key ON memories(preference_key)")
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    id UNINDEXED,
                    title,
                    content,
                    tags_text
                )
                """
            )
            self._backfill_fts_if_needed(conn)
            conn.commit()
        try:
            os.chmod(self.db_path, 0o600)
        except Exception:
            pass

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Migración compatible hacia adelante para bases de datos existentes."""
        existing_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(memories)").fetchall()
        }
        migrations = (
            ("status", "TEXT NOT NULL DEFAULT 'valid'"),
            ("valid_until", "TEXT DEFAULT NULL"),
            ("importance", "REAL NOT NULL DEFAULT 0.5"),
            ("preference_source", "TEXT DEFAULT NULL"),
            ("preference_scope", "TEXT DEFAULT NULL"),
            ("preference_key", "TEXT DEFAULT NULL"),
            ("superseded_by", "TEXT DEFAULT NULL"),
            ("evidence_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("relations_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("embedding_json", "TEXT DEFAULT NULL"),
        )
        for col_name, col_def in migrations:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE memories ADD COLUMN {col_name} {col_def}")

    @staticmethod
    def _sync_fts_row(conn: sqlite3.Connection, mem_id: str, title: str, content: str, context_json: str) -> None:
        try:
            ctx = json.loads(context_json or "{}")
            tags_text = " ".join(str(x) for x in (ctx.get("tags") or []))
        except Exception:
            tags_text = ""
        conn.execute("DELETE FROM memories_fts WHERE id = ?", (mem_id,))
        conn.execute(
            "INSERT INTO memories_fts (id, title, content, tags_text) VALUES (?, ?, ?, ?)",
            (mem_id, title, content, tags_text),
        )

    def _backfill_fts_if_needed(self, conn: sqlite3.Connection) -> None:
        mem_cnt = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        fts_cnt = conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0]
        if mem_cnt > 0 and fts_cnt == 0:
            rows = conn.execute("SELECT id, title, content, context_json FROM memories").fetchall()
            for r in rows:
                self._sync_fts_row(conn, r["id"], r["title"], r["content"], r["context_json"])

    def seed_defaults_if_empty(self) -> None:
        """Registra invariantes verificadas de usuario y arquitectura si la base está vacía."""
        with self._connect() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        if cnt > 0:
            return
        self.store_memory(
            tier="user",
            category="user_preference",
            title="Perfil de Hardware RTX 4060 Laptop (8 GB VRAM) y Garuda Linux",
            content="Hardware objetivo: NVIDIA RTX 4060 Laptop (8188 MiB VRAM) y 32 GiB RAM sobre Garuda/Arch Linux. Regla estricta: OLLAMA_MAX_LOADED_MODELS=1, delegación secuencial con modelos locales.",
            provenance="system:compatibility.json",
            project_path="*",
            context={"tags": ["hardware", "vram", "rtx4060", "garuda", "ollama"], "evidence_ref": "compatibility.json#L13-L19"},
            confidence=1.0,
        )
        self.store_memory(
            tier="project",
            category="architectural_decision",
            title="ADR-001: Separación Motor OpenCode v2.3.2 vs Capa Distribución Saghet",
            content="No modificar el binario /usr/bin/opencode ni meter Cordis en el núcleo. Toda extensión usa ~/.config/opencode/, ACP stdio y servicios desacoplados.",
            provenance="architect:docs/ARCHITECTURE.md",
            project_path=str(REPO_DIR),
            context={"tags": ["architecture", "upstream", "acp", "opencode"], "evidence_ref": "docs/ARCHITECTURE.md#L40-L45"},
            confidence=0.98,
        )

    def store_memory(
        self,
        tier: str,
        category: str,
        title: str,
        content: str,
        provenance: str,
        project_path: str = "*",
        session_id: str = "",
        context: dict | None = None,
        confidence: float = 0.85,
        similarity_threshold: float = 0.82,
        status: str = "valid",
        valid_until: str | None = None,
        importance: float = 0.5,
        preference_source: str | None = None,
        preference_scope: str | None = None,
        preference_key: str | None = None,
        evidence: dict | None = None,
        relations: list[dict] | None = None,
    ) -> dict:
        """
        Guarda un recuerdo jerárquico con deduplicación exacta por huella y deduplicación
        difusa por similitud Jaccard (>= 0.82) dentro del mismo nivel, proyecto y estado activo.
        Rechaza credenciales o secretos detectados.
        """
        norm_tier = tier if tier in VALID_TIERS else "experience"
        norm_cat = category if category in VALID_CATEGORIES else "verified_execution"
        norm_status = status if status in VALID_STATUSES else "valid"
        clean_title = (title or "").strip()[:200] or "Recuerdo Saghet"
        clean_content = (content or "").strip()
        clean_prov = (provenance or "saghet-orchestrator").strip()
        norm_proj = str(Path(project_path).resolve()) if project_path and project_path != "*" else "*"
        bounded_conf = max(0.0, min(1.0, round(float(confidence), 3)))
        bounded_imp = max(0.0, min(1.0, round(float(importance), 3)))

        if not clean_content:
            return {"ok": False, "error": "El contenido del recuerdo no puede estar vacío"}
        if contains_sensitive_secret(clean_content) or contains_sensitive_secret(clean_title):
            return {"ok": False, "error": "Bloqueado por privacidad: el recuerdo contiene credenciales o secretos"}

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        now_ms = int(time.time() * 1000)
        ctx = dict(context or {})
        ctx.setdefault("category", norm_cat)
        ctx.setdefault("project_path", norm_proj)
        if session_id:
            ctx.setdefault("session_id", session_id)
        ev_json = json.dumps(evidence or {}, ensure_ascii=False)
        rel_json = json.dumps(relations or [], ensure_ascii=False)
        tags_str = " ".join(str(x) for x in (ctx.get("tags") or []))
        emb_vec = compute_embedding(f"{clean_title} {clean_content} {tags_str}")
        emb_json = json.dumps(emb_vec)

        fp = compute_content_fingerprint(norm_tier, norm_cat, norm_proj, f"{clean_title} {clean_content}")
        new_tokens = tokenize_meaningful(f"{clean_title} {clean_content}")

        with self._connect() as conn:
            # 1. Búsqueda de duplicado exacto por fingerprint (solo en recuerdos activos)
            existing = conn.execute(
                "SELECT * FROM memories WHERE fingerprint = ? AND tier = ? AND project_path = ? AND status IN ('valid', 'provisional')",
                (fp, norm_tier, norm_proj),
            ).fetchone()

            # 2. Búsqueda de duplicado semántico/léxico en el mismo tier y proyecto
            if existing is None:
                candidates = conn.execute(
                    "SELECT * FROM memories WHERE tier = ? AND category = ? AND project_path = ? AND status IN ('valid', 'provisional') ORDER BY epoch_ms DESC LIMIT 40",
                    (norm_tier, norm_cat, norm_proj),
                ).fetchall()
                for cand in candidates:
                    cand_tokens = tokenize_meaningful(f"{cand['title']} {cand['content']}")
                    if jaccard_similarity(new_tokens, cand_tokens) >= similarity_threshold:
                        existing = cand
                        break

            if existing is not None:
                mem_id = existing["id"]
                new_count = int(existing["occurrence_count"]) + 1
                merged_conf = max(float(existing["confidence"]), bounded_conf)
                merged_imp = max(float(existing["importance"] if existing["importance"] is not None else 0.5), bounded_imp)
                # Si era provisional por observación aislada y se repite, puede conservar o promover estado según caller
                merged_status = existing["status"]
                if norm_status == "valid":
                    merged_status = "valid"
                elif existing["status"] == "provisional" and new_count >= 2 and preference_source == "inferred":
                    merged_status = "valid"
                try:
                    old_ctx = json.loads(existing["context_json"])
                except Exception:
                    old_ctx = {}
                old_tags = set(old_ctx.get("tags") or [])
                new_tags = set(ctx.get("tags") or [])
                old_ctx.update(ctx)
                if old_tags or new_tags:
                    old_ctx["tags"] = sorted(old_tags | new_tags)

                merged_ctx_json = json.dumps(old_ctx, ensure_ascii=False)
                conn.execute(
                    """
                    UPDATE memories
                    SET content = ?, provenance = ?, context_json = ?, confidence = ?,
                        importance = ?, status = ?, valid_until = COALESCE(?, valid_until),
                        preference_source = COALESCE(?, preference_source),
                        preference_scope = COALESCE(?, preference_scope),
                        preference_key = COALESCE(?, preference_key),
                        embedding_json = ?, occurrence_count = ?, updated_at = ?, epoch_ms = ?
                    WHERE id = ?
                    """,
                    (
                        clean_content,
                        clean_prov,
                        merged_ctx_json,
                        merged_conf,
                        merged_imp,
                        merged_status,
                        valid_until,
                        preference_source,
                        preference_scope,
                        preference_key,
                        emb_json,
                        new_count,
                        now_iso,
                        now_ms,
                        mem_id,
                    ),
                )
                self._sync_fts_row(conn, mem_id, existing["title"], clean_content, merged_ctx_json)
                conn.commit()
                return {
                    "ok": True,
                    "id": mem_id,
                    "deduplicated": True,
                    "tier": norm_tier,
                    "category": norm_cat,
                    "status": merged_status,
                    "occurrence_count": new_count,
                    "confidence": merged_conf,
                    "updated_at": now_iso,
                }

            mem_id = f"mem_{uuid.uuid4().hex[:12]}"
            ctx_json = json.dumps(ctx, ensure_ascii=False)
            conn.execute(
                """
                INSERT INTO memories (
                    id, tier, category, title, content, provenance,
                    project_path, session_id, context_json, confidence,
                    fingerprint, occurrence_count, created_at, updated_at, epoch_ms,
                    status, valid_until, importance, preference_source,
                    preference_scope, preference_key, superseded_by, evidence_json, relations_json, embedding_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    mem_id,
                    norm_tier,
                    norm_cat,
                    clean_title,
                    clean_content,
                    clean_prov,
                    norm_proj,
                    session_id or "",
                    ctx_json,
                    bounded_conf,
                    fp,
                    now_iso,
                    now_iso,
                    now_ms,
                    norm_status,
                    valid_until,
                    bounded_imp,
                    preference_source,
                    preference_scope,
                    preference_key,
                    ev_json,
                    rel_json,
                    emb_json,
                ),
            )
            self._sync_fts_row(conn, mem_id, clean_title, clean_content, ctx_json)
            conn.commit()

        return {
            "ok": True,
            "id": mem_id,
            "deduplicated": False,
            "tier": norm_tier,
            "category": norm_cat,
            "status": norm_status,
            "occurrence_count": 1,
            "confidence": bounded_conf,
            "created_at": now_iso,
        }

    @staticmethod
    def _fts_bm25_scores(conn: sqlite3.Connection, query: str) -> dict[str, float]:
        """Consulta FTS5 BM25 sobre `memories_fts` y normaliza puntuaciones a [0.0, 1.0]."""
        tokens = sorted(expand_semantic_tokens(tokenize_meaningful(query)))
        if not tokens:
            return {}
        fts_terms = [re.sub(r"[^a-zA-Z0-9_]", "", t) for t in tokens[:12]]
        fts_terms = [t for t in fts_terms if len(t) >= 2]
        if not fts_terms:
            return {}
        match_expr = " OR ".join(f'"{t}"' for t in fts_terms)
        scores: dict[str, float] = {}
        try:
            rows = conn.execute(
                "SELECT id, bm25(memories_fts) AS rank_val FROM memories_fts WHERE memories_fts MATCH ? LIMIT 80",
                (match_expr,),
            ).fetchall()
            for r in rows:
                # En SQLite FTS5, bm25() devuelve valores negativos (más negativo = mejor coincidencia)
                raw = abs(float(r["rank_val"] or 0.0))
                scores[r["id"]] = min(1.0, raw / (1.0 + raw) + 0.25)
        except Exception:
            return {}
        return scores

    def retrieve_relevant_memories(
        self,
        query: str,
        project_path: str = "*",
        session_id: str = "",
        tiers: list[str] | None = None,
        min_confidence: float = 0.60,
        min_relevance: float = 0.14,
        limit: int = 6,
        include_inactive: bool = False,
        include_provisional: bool = True,
    ) -> list[dict]:
        """
        Recuperación híbrida: BM25 (FTS5) + expansión semántica bilingüe + embeddings locales +
        metadatos/etiquetas + recencia + confianza + importancia + relaciones entre recuerdos.
        Filtra recuerdos obsoletos (`superseded`/`invalidated`) y por proyecto/sesión.
        """
        norm_proj = str(Path(project_path).resolve()) if project_path and project_path != "*" else "*"
        active_tiers = [t for t in (tiers or list(VALID_TIERS)) if t in VALID_TIERS] or list(VALID_TIERS)
        query_tokens = tokenize_meaningful(query)
        expanded_query_tokens = expand_semantic_tokens(query_tokens)
        query_vec = compute_embedding(query) if query_tokens else []
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        now_ms = int(time.time() * 1000)

        placeholders = ",".join("?" for _ in active_tiers)
        allowed_statuses = list(VALID_STATUSES) if include_inactive else (["valid", "provisional"] if include_provisional else ["valid"])
        st_placeholders = ",".join("?" for _ in allowed_statuses)
        params: list = [*active_tiers, *allowed_statuses, float(min_confidence)]

        with self._connect() as conn:
            bm25_map = self._fts_bm25_scores(conn, query) if query_tokens else {}
            rows = conn.execute(
                f"SELECT * FROM memories WHERE tier IN ({placeholders}) AND status IN ({st_placeholders}) AND confidence >= ? ORDER BY epoch_ms DESC LIMIT 200",
                params,
            ).fetchall()

        scored: list[dict] = []
        linked_boost_targets: set[str] = set()
        for r in rows:
            r_tier = r["tier"]
            r_proj = r["project_path"]
            valid_until = r["valid_until"]
            if not include_inactive and valid_until and valid_until < now_iso:
                continue

            # Aislamiento estricto por proyecto: recuerdos de tier 'project' de otro proyecto se excluyen
            if r_tier == "project" and norm_proj != "*" and r_proj not in {"*", norm_proj}:
                continue
            # Aislamiento por sesión: recuerdos de tier 'session' de otra sesión se excluyen si se especificó session_id
            if r_tier == "session" and session_id and r["session_id"] and r["session_id"] != session_id:
                continue

            try:
                ctx = json.loads(r["context_json"])
            except Exception:
                ctx = {}
            try:
                rels = json.loads(r["relations_json"] or "[]")
            except Exception:
                rels = []

            tags_text = " ".join(str(x) for x in (ctx.get("tags") or []))
            full_mem_text = f"{r['title']} {r['content']} {tags_text} {r['category']} {r['preference_key'] or ''}"
            mem_tokens = tokenize_meaningful(full_mem_text)
            expanded_mem_tokens = expand_semantic_tokens(mem_tokens)

            if not query_tokens:
                bm25_score = 0.5
                lexical_score = 0.5
                semantic_score = 0.5
            else:
                direct_overlap = len(query_tokens & mem_tokens)
                expanded_overlap = len(expanded_query_tokens & expanded_mem_tokens)
                lexical_score = (
                    (direct_overlap * 1.0 + max(0, expanded_overlap - direct_overlap) * 0.65)
                    / max(1, min(len(query_tokens), 8))
                )
                lexical_score = min(1.0, lexical_score)
                bm25_score = bm25_map.get(r["id"], 0.0)

                try:
                    mem_vec = json.loads(r["embedding_json"]) if r["embedding_json"] else compute_local_ngram_embedding(full_mem_text)
                except Exception:
                    mem_vec = compute_local_ngram_embedding(full_mem_text)
                semantic_score = cosine_similarity(query_vec, mem_vec)

                # Descartar ruido cuando no hay ni coincidencia léxica/BM25 ni similitud semántica alta
                if direct_overlap == 0 and expanded_overlap == 0 and bm25_score == 0.0 and semantic_score < 0.48:
                    continue

            # Recencia (decaimiento suave por días)
            age_days = max(0.0, (now_ms - int(r["epoch_ms"] or now_ms)) / 86_400_000.0)
            recency_score = math.exp(-age_days / 30.0)

            conf = float(r["confidence"])
            imp = float(r["importance"] if r["importance"] is not None else 0.5)
            # No usar recurrencia como única medida de verdad: acotar su aporte máximo
            occ_boost = min(0.06, (int(r["occurrence_count"]) - 1) * 0.015)
            explicit_boost = 0.07 if r["preference_source"] == "explicit" else 0.0
            provisional_penalty = -0.10 if r["status"] == "provisional" else 0.0

            hybrid_match = max(bm25_score, lexical_score) * 0.55 + (semantic_score * 0.45)
            relevance_score = round(
                max(
                    0.0,
                    (hybrid_match * 0.60)
                    + (conf * 0.18)
                    + (imp * 0.10)
                    + (recency_score * 0.12)
                    + occ_boost
                    + explicit_boost
                    + provisional_penalty,
                ),
                3,
            )

            if relevance_score < min_relevance:
                continue

            if hybrid_match >= 0.35:
                for rel in rels:
                    if isinstance(rel, dict) and rel.get("type") in {"supports", "derived_from", "related_to"} and rel.get("target_id"):
                        linked_boost_targets.add(str(rel["target_id"]))

            scored.append(
                {
                    "id": r["id"],
                    "tier": r_tier,
                    "category": r["category"],
                    "title": r["title"],
                    "content": r["content"],
                    "provenance": r["provenance"],
                    "project_path": r_proj,
                    "session_id": r["session_id"],
                    "context": ctx,
                    "confidence": conf,
                    "importance": imp,
                    "status": r["status"],
                    "valid_until": valid_until,
                    "preference_source": r["preference_source"],
                    "preference_scope": r["preference_scope"],
                    "preference_key": r["preference_key"],
                    "superseded_by": r["superseded_by"],
                    "relations": rels,
                    "occurrence_count": int(r["occurrence_count"]),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "relevance_score": relevance_score,
                }
            )

        if linked_boost_targets:
            for item in scored:
                if item["id"] in linked_boost_targets:
                    item["relevance_score"] = round(min(1.2, item["relevance_score"] + 0.06), 3)

        scored.sort(
            key=lambda x: (
                x["relevance_score"],
                1 if x.get("preference_source") == "explicit" else 0,
                x["confidence"],
                x["importance"],
            ),
            reverse=True,
        )
        return scored[: max(1, min(25, limit))]

    def inspect_memories(
        self,
        tier: str | None = None,
        category: str | None = None,
        project_path: str | None = None,
        status: str | None = None,
        preference_key: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Permite inspeccionar recuerdos con filtros explícitos (incluyendo historial superseded)."""
        clauses: list[str] = []
        params: list = []
        if tier:
            clauses.append("tier = ?")
            params.append(tier)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if project_path:
            norm_proj = str(Path(project_path).resolve()) if project_path != "*" else "*"
            clauses.append("project_path = ?")
            params.append(norm_proj)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if preference_key:
            clauses.append("preference_key = ?")
            params.append(preference_key)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(200, int(limit))))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM memories {where_sql} ORDER BY epoch_ms DESC LIMIT ?",
                params,
            ).fetchall()

        results: list[dict] = []
        for r in rows:
            try:
                ctx = json.loads(r["context_json"])
            except Exception:
                ctx = {}
            results.append(
                {
                    "id": r["id"],
                    "tier": r["tier"],
                    "category": r["category"],
                    "title": r["title"],
                    "content": r["content"],
                    "provenance": r["provenance"],
                    "project_path": r["project_path"],
                    "session_id": r["session_id"],
                    "context": ctx,
                    "confidence": float(r["confidence"]),
                    "importance": float(r["importance"] if r["importance"] is not None else 0.5),
                    "status": r["status"],
                    "valid_until": r["valid_until"],
                    "preference_source": r["preference_source"],
                    "preference_scope": r["preference_scope"],
                    "preference_key": r["preference_key"],
                    "superseded_by": r["superseded_by"],
                    "occurrence_count": int(r["occurrence_count"]),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                }
            )
        return results

    def invalidate_memory(
        self,
        memory_id: str,
        reason: str = "",
        new_status: str = "superseded",
        superseded_by: str | None = None,
    ) -> dict:
        """Marca un recuerdo como superseded o invalidated conservando su historial."""
        target_status = new_status if new_status in {"superseded", "invalidated"} else "superseded"
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
            if row is None:
                return {"ok": False, "error": f"Recuerdo no encontrado: {memory_id}"}
            try:
                ctx = json.loads(row["context_json"])
            except Exception:
                ctx = {}
            if reason:
                ctx["invalidation_reason"] = reason
            ctx["invalidated_at"] = now_iso
            conn.execute(
                "UPDATE memories SET status = ?, superseded_by = ?, context_json = ?, updated_at = ? WHERE id = ?",
                (target_status, superseded_by, json.dumps(ctx, ensure_ascii=False), now_iso, memory_id),
            )
            conn.commit()
        return {"ok": True, "id": memory_id, "status": target_status, "superseded_by": superseded_by}

    def correct_memory(
        self,
        memory_id: str,
        new_content: str,
        provenance: str = "user:correction",
        new_title: str | None = None,
        confidence: float = 0.98,
    ) -> dict:
        """Corrige un recuerdo existente de forma segura manteniendo registro del cambio."""
        clean_content = (new_content or "").strip()
        if not clean_content:
            return {"ok": False, "error": "El nuevo contenido no puede estar vacío"}
        if contains_sensitive_secret(clean_content) or (new_title and contains_sensitive_secret(new_title)):
            return {"ok": False, "error": "Bloqueado por privacidad: contiene credenciales o secretos"}

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        now_ms = int(time.time() * 1000)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
            if row is None:
                return {"ok": False, "error": f"Recuerdo no encontrado: {memory_id}"}
            try:
                ctx = json.loads(row["context_json"])
            except Exception:
                ctx = {}
            history = list(ctx.get("edit_history") or [])
            history.append({"previous_content": row["content"], "changed_at": now_iso, "provenance": provenance})
            ctx["edit_history"] = history[-10:]

            title_to_use = (new_title or row["title"]).strip()[:200]
            ctx_json = json.dumps(ctx, ensure_ascii=False)
            fp = compute_content_fingerprint(row["tier"], row["category"], row["project_path"], f"{title_to_use} {clean_content}")
            emb_json = json.dumps(compute_embedding(f"{title_to_use} {clean_content}"))
            conn.execute(
                """
                UPDATE memories
                SET title = ?, content = ?, provenance = ?, confidence = ?, status = 'valid',
                    fingerprint = ?, context_json = ?, embedding_json = ?, updated_at = ?, epoch_ms = ?
                WHERE id = ?
                """,
                (
                    title_to_use,
                    clean_content,
                    provenance,
                    max(0.0, min(1.0, float(confidence))),
                    fp,
                    ctx_json,
                    emb_json,
                    now_iso,
                    now_ms,
                    memory_id,
                ),
            )
            self._sync_fts_row(conn, memory_id, title_to_use, clean_content, ctx_json)
            conn.commit()
        return {"ok": True, "id": memory_id, "updated_at": now_iso, "status": "valid"}

    def delete_memory(self, memory_id: str) -> dict:
        """Elimina permanentemente un recuerdo por ID (derecho de borrado y privacidad)."""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.execute("DELETE FROM memories_fts WHERE id = ?", (memory_id,))
            conn.commit()
            deleted = cur.rowcount > 0
        if not deleted:
            return {"ok": False, "error": f"Recuerdo no encontrado: {memory_id}"}
        return {"ok": True, "id": memory_id, "deleted": True}

    def link_memories(self, source_id: str, target_id: str, relation_type: str = "related_to") -> dict:
        """Crea una relación tipada entre dos recuerdos (`supports`, `contradicts`, `supersedes`, `derived_from`, `related_to`)."""
        valid_rel = relation_type if relation_type in {"supports", "contradicts", "supersedes", "derived_from", "related_to"} else "related_to"
        with self._connect() as conn:
            src = conn.execute("SELECT id, relations_json FROM memories WHERE id = ?", (source_id,)).fetchone()
            tgt = conn.execute("SELECT id FROM memories WHERE id = ?", (target_id,)).fetchone()
            if src is None or tgt is None:
                return {"ok": False, "error": "Recuerdo origen o destino no encontrado"}
            try:
                rels = json.loads(src["relations_json"] or "[]")
            except Exception:
                rels = []
            entry = {"target_id": target_id, "type": valid_rel}
            if entry not in rels:
                rels.append(entry)
                conn.execute(
                    "UPDATE memories SET relations_json = ? WHERE id = ?",
                    (json.dumps(rels, ensure_ascii=False), source_id),
                )
                conn.commit()
        return {"ok": True, "source_id": source_id, "target_id": target_id, "type": valid_rel}

    def build_contextual_memory_pack(
        self,
        objective: str,
        project_path: str = "*",
        session_id: str = "",
        max_chars: int = 3200,
    ) -> dict:
        """
        Construye un paquete compacto y no redundante de contexto relevante para un objetivo dado,
        evitando inyectar toda la memoria en cada prompt.
        """
        user_mems = self.retrieve_relevant_memories(
            query=objective, project_path=project_path, tiers=["user"], include_provisional=False, limit=4
        )
        project_mems = self.retrieve_relevant_memories(
            query=objective, project_path=project_path, tiers=["project"], include_provisional=False, limit=4
        )
        exp_mems = self.retrieve_relevant_memories(
            query=objective, project_path=project_path, tiers=["experience"], include_provisional=False, limit=4
        )
        sess_mems = (
            self.retrieve_relevant_memories(
                query=objective, project_path=project_path, session_id=session_id, tiers=["session"], limit=2
            )
            if session_id
            else []
        )

        lines: list[str] = []
        used_chars = 0
        included_ids: list[str] = []
        for label, group in (("USER", user_mems), ("PROJECT", project_mems), ("EXPERIENCE", exp_mems), ("SESSION", sess_mems)):
            for m in group:
                snippet = f"[{label}:{m['category']}] {m['title']} — {m['content'][:220].replace(chr(10), ' ')}"
                if used_chars + len(snippet) + 1 > max_chars:
                    break
                lines.append(snippet)
                used_chars += len(snippet) + 1
                included_ids.append(m["id"])

        return {
            "project_path": project_path,
            "included_count": len(included_ids),
            "included_ids": included_ids,
            "char_count": used_chars,
            "context_text": "\n".join(lines),
        }

    def consolidate_experiences(
        self,
        project_path: str = "*",
        min_occurrences: int = 2,
        min_confidence: float = 0.85,
    ) -> dict:
        """
        Consolida experiencias verificadas repetidas (`verified_execution` / `proven_solution`)
        en conocimiento reutilizable (`consolidated_procedure`), preservando procedencia y evidencia.
        """
        norm_proj = str(Path(project_path).resolve()) if project_path and project_path != "*" else "*"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memories
                WHERE tier = 'experience'
                  AND category IN ('verified_execution', 'proven_solution')
                  AND status = 'valid'
                  AND confidence >= ?
                  AND (? = '*' OR project_path IN ('*', ?))
                ORDER BY epoch_ms DESC LIMIT 100
                """,
                (float(min_confidence), norm_proj, norm_proj),
            ).fetchall()

        consolidated: list[dict] = []
        for r in rows:
            if int(r["occurrence_count"]) < min_occurrences:
                continue
            try:
                ctx = json.loads(r["context_json"])
            except Exception:
                ctx = {}
            tags = sorted({"consolidated_procedure", *(ctx.get("tags") or [])})
            res = self.store_memory(
                tier="project" if r["project_path"] != "*" else "experience",
                category="consolidated_procedure",
                title=f"Procedimiento verificado: {r['title'][:120]}",
                content=f"Estrategia validada ({r['occurrence_count']}x, confianza {r['confidence']}): {r['content'][:500]}",
                provenance=f"consolidation:{r['provenance']}",
                project_path=r["project_path"],
                context={"tags": tags, "source_memory_id": r["id"], "occurrence_count": int(r["occurrence_count"])},
                confidence=min(0.99, float(r["confidence"])),
                status="valid",
                importance=0.88,
                evidence={"source_memory_id": r["id"], "occurrence_count": int(r["occurrence_count"])},
                relations=[{"target_id": r["id"], "type": "derived_from"}],
            )
            if res.get("ok"):
                consolidated.append(res)

        return {"ok": True, "consolidated_count": len(consolidated), "items": consolidated}

    def get_summary(self) -> dict:
        self.seed_defaults_if_empty()
        with self._connect() as conn:
            tier_rows = conn.execute(
                "SELECT tier, COUNT(*) as cnt, AVG(confidence) as avg_conf FROM memories GROUP BY tier"
            ).fetchall()
            cat_rows = conn.execute(
                "SELECT category, COUNT(*) as cnt, SUM(occurrence_count) as total_occ FROM memories GROUP BY category"
            ).fetchall()
            recent_rows = conn.execute(
                "SELECT * FROM memories ORDER BY epoch_ms DESC LIMIT 20"
            ).fetchall()

        tiers_summary = {t: {"count": 0, "avg_confidence": 0.0} for t in VALID_TIERS}
        for r in tier_rows:
            tiers_summary[r["tier"]] = {
                "count": int(r["cnt"]),
                "avg_confidence": round(float(r["avg_conf"] or 0.0), 3),
            }

        categories_summary = {
            r["category"]: {"unique_memories": int(r["cnt"]), "total_occurrences": int(r["total_occ"] or 0)}
            for r in cat_rows
        }

        recent = []
        for r in recent_rows:
            try:
                ctx = json.loads(r["context_json"])
            except Exception:
                ctx = {}
            recent.append(
                {
                    "id": r["id"],
                    "tier": r["tier"],
                    "category": r["category"],
                    "title": r["title"],
                    "content": r["content"],
                    "provenance": r["provenance"],
                    "project_path": r["project_path"],
                    "confidence": float(r["confidence"]),
                    "occurrence_count": int(r["occurrence_count"]),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "context": ctx,
                }
            )

        return {
            "db_path": str(self.db_path),
            "tiers": tiers_summary,
            "categories": categories_summary,
            "recent_memories": recent,
            "ecosystem": inspect_opencode_mem_and_dcp(),
        }
