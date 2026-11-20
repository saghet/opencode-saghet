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
import os
import re
import sqlite3
import time
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
)

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
    tokens = {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}
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
                    epoch_ms INTEGER NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_tier ON memories(tier)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_path)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_fingerprint ON memories(fingerprint)")
            conn.commit()
        try:
            os.chmod(self.db_path, 0o600)
        except Exception:
            pass

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
    ) -> dict:
        """
        Guarda un recuerdo jerárquico con deduplicación exacta por huella y deduplicación
        difusa por similitud Jaccard (>= 0.82) dentro del mismo nivel y proyecto.
        """
        norm_tier = tier if tier in VALID_TIERS else "experience"
        norm_cat = category if category in VALID_CATEGORIES else "verified_execution"
        clean_title = (title or "").strip()[:200] or "Recuerdo Saghet"
        clean_content = (content or "").strip()
        clean_prov = (provenance or "saghet-orchestrator").strip()
        norm_proj = str(Path(project_path).resolve()) if project_path and project_path != "*" else "*"
        bounded_conf = max(0.0, min(1.0, round(float(confidence), 3)))

        if not clean_content:
            return {"ok": False, "error": "El contenido del recuerdo no puede estar vacío"}

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        now_ms = int(time.time() * 1000)
        ctx = dict(context or {})
        ctx.setdefault("category", norm_cat)
        ctx.setdefault("project_path", norm_proj)
        if session_id:
            ctx.setdefault("session_id", session_id)

        fp = compute_content_fingerprint(norm_tier, norm_cat, norm_proj, f"{clean_title} {clean_content}")
        new_tokens = tokenize_meaningful(f"{clean_title} {clean_content}")

        with self._connect() as conn:
            # 1. Búsqueda de duplicado exacto por fingerprint
            existing = conn.execute(
                "SELECT * FROM memories WHERE fingerprint = ? AND tier = ? AND project_path = ?",
                (fp, norm_tier, norm_proj),
            ).fetchone()

            # 2. Búsqueda de duplicado semántico/léxico en el mismo tier y proyecto
            if existing is None:
                candidates = conn.execute(
                    "SELECT * FROM memories WHERE tier = ? AND category = ? AND project_path = ? ORDER BY epoch_ms DESC LIMIT 40",
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
                try:
                    old_ctx = json.loads(existing["context_json"])
                except Exception:
                    old_ctx = {}
                old_tags = set(old_ctx.get("tags") or [])
                new_tags = set(ctx.get("tags") or [])
                old_ctx.update(ctx)
                if old_tags or new_tags:
                    old_ctx["tags"] = sorted(old_tags | new_tags)

                conn.execute(
                    """
                    UPDATE memories
                    SET content = ?, provenance = ?, context_json = ?, confidence = ?,
                        occurrence_count = ?, updated_at = ?, epoch_ms = ?
                    WHERE id = ?
                    """,
                    (
                        clean_content,
                        clean_prov,
                        json.dumps(old_ctx, ensure_ascii=False),
                        merged_conf,
                        new_count,
                        now_iso,
                        now_ms,
                        mem_id,
                    ),
                )
                conn.commit()
                return {
                    "ok": True,
                    "id": mem_id,
                    "deduplicated": True,
                    "tier": norm_tier,
                    "category": norm_cat,
                    "occurrence_count": new_count,
                    "confidence": merged_conf,
                    "updated_at": now_iso,
                }

            mem_id = f"mem_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO memories (
                    id, tier, category, title, content, provenance,
                    project_path, session_id, context_json, confidence,
                    fingerprint, occurrence_count, created_at, updated_at, epoch_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
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
                    json.dumps(ctx, ensure_ascii=False),
                    bounded_conf,
                    fp,
                    now_iso,
                    now_iso,
                    now_ms,
                ),
            )
            conn.commit()

        return {
            "ok": True,
            "id": mem_id,
            "deduplicated": False,
            "tier": norm_tier,
            "category": norm_cat,
            "occurrence_count": 1,
            "confidence": bounded_conf,
            "created_at": now_iso,
        }

    def retrieve_relevant_memories(
        self,
        query: str,
        project_path: str = "*",
        session_id: str = "",
        tiers: list[str] | None = None,
        min_confidence: float = 0.60,
        min_relevance: float = 0.14,
        limit: int = 6,
    ) -> list[dict]:
        """
        Recupera recuerdos relevantes filtrando por nivel de confianza, aislamiento de proyecto
        y solapamiento léxico/etiquetas. Descarta recuerdos con relevancia < min_relevance.
        """
        norm_proj = str(Path(project_path).resolve()) if project_path and project_path != "*" else "*"
        active_tiers = [t for t in (tiers or list(VALID_TIERS)) if t in VALID_TIERS] or list(VALID_TIERS)
        query_tokens = tokenize_meaningful(query)

        placeholders = ",".join("?" for _ in active_tiers)
        params: list = [*active_tiers, float(min_confidence)]

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM memories WHERE tier IN ({placeholders}) AND confidence >= ? ORDER BY epoch_ms DESC LIMIT 200",
                params,
            ).fetchall()

        scored: list[dict] = []
        for r in rows:
            r_tier = r["tier"]
            r_proj = r["project_path"]

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

            tags_text = " ".join(str(x) for x in (ctx.get("tags") or []))
            mem_tokens = tokenize_meaningful(f"{r['title']} {r['content']} {tags_text} {r['category']}")

            if not query_tokens:
                lexical_score = 0.5
            else:
                overlap = len(query_tokens & mem_tokens)
                if overlap == 0:
                    continue
                lexical_score = overlap / max(1, min(len(query_tokens), 8))

            # Ponderar relevancia léxica con nivel de confianza y recurrencia comprobada
            conf = float(r["confidence"])
            occ_boost = min(0.15, (int(r["occurrence_count"]) - 1) * 0.03)
            relevance_score = round((lexical_score * 0.72) + (conf * 0.28) + occ_boost, 3)

            if relevance_score < min_relevance:
                continue

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
                    "occurrence_count": int(r["occurrence_count"]),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "relevance_score": relevance_score,
                }
            )

        scored.sort(key=lambda x: (x["relevance_score"], x["confidence"], x["occurrence_count"]), reverse=True)
        return scored[: max(1, min(25, limit))]

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
