#!/usr/bin/env python3
"""
Project Intelligence & Continuity Engine — OpenCode-Saghet Cognitive V2 (Fase 3).

Indexación incremental de repositorios en SQLite (AST Python, símbolos, imports,
referencias, pruebas asociadas, historial Git y decisiones) + reconstrucción real
de continuidad entre sesiones, sin motores de grafos pesados ni dependencias externas.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path

from scripts.memory.hierarchical_memory import HierarchicalMemoryStore

SAGHET_STATE_DIR = Path.home() / ".local" / "share" / "opencode-saghet"
DEFAULT_PROJECT_INDEX_DB = SAGHET_STATE_DIR / "project_intelligence.db"

IGNORED_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    "target",
    ".next",
    ".cache",
}
INDEXABLE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".md", ".json", ".jsonc", ".toml"}
MAX_FILE_BYTES = 512 * 1024

_JS_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:function\s+([A-Za-z_]\w*)|class\s+([A-Za-z_]\w*)|const\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?\()"
)
_JS_IMPORT_RE = re.compile(r"""(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\))""")
_MD_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()[:24]


def _run_git(repo_dir: Path, args: list[str], timeout: float = 4.0) -> str:
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return res.stdout.strip() if res.returncode == 0 else ""
    except Exception:
        return ""


class ProjectIntelligenceEngine:
    """
    Motor de Inteligencia y Continuidad de Proyectos sobre SQLite local.
    Provee indexación incremental, análisis de impacto, mapa de pruebas y continuidad real.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        memory_store: HierarchicalMemoryStore | None = None,
    ) -> None:
        self.db_path = Path(db_path or DEFAULT_PROJECT_INDEX_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory = memory_store
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return contextlib.closing(conn)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS indexed_files (
                    project_path TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    ext TEXT NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    is_test INTEGER NOT NULL DEFAULT 0,
                    line_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (project_path, rel_path)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS symbols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_path TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    start_line INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    signature TEXT NOT NULL,
                    docstring TEXT NOT NULL,
                    calls_json TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS imports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_path TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    module_name TEXT NOT NULL,
                    imported_names TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_continuity (
                    project_path TEXT PRIMARY KEY,
                    goals_json TEXT NOT NULL DEFAULT '[]',
                    architecture_summary TEXT NOT NULL DEFAULT '',
                    completed_features_json TEXT NOT NULL DEFAULT '[]',
                    pending_features_json TEXT NOT NULL DEFAULT '[]',
                    known_issues_json TEXT NOT NULL DEFAULT '[]',
                    decisions_json TEXT NOT NULL DEFAULT '[]',
                    test_summary_json TEXT NOT NULL DEFAULT '{}',
                    git_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    next_recommended_step TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS project_fts USING fts5(
                    project_path UNINDEXED,
                    rel_path,
                    symbols_text,
                    summary_text
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sym_proj_name ON symbols(project_path, name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_imp_proj_mod ON imports(project_path, module_name)")
            conn.commit()
        try:
            os.chmod(self.db_path, 0o600)
        except Exception:
            pass

    @staticmethod
    def _is_test_file(rel_path: str) -> bool:
        low = rel_path.lower()
        name = Path(low).name
        return (
            name.startswith("test_")
            or name.endswith("_test.py")
            or ".test." in name
            or ".spec." in name
            or "/tests/" in f"/{low}"
            or low.startswith("tests/")
        )

    @staticmethod
    def _extract_python_structure(text: str) -> tuple[list[dict], list[dict]]:
        symbols: list[dict] = []
        imports: list[dict] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return symbols, imports

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({"module": alias.name, "names": alias.asname or alias.name})
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                names = ", ".join(a.name for a in node.names)
                if mod:
                    imports.append({"module": mod, "names": names})

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [a.arg for a in node.args.args]
                calls = sorted(
                    {
                        n.func.id if isinstance(n.func, ast.Name) else (n.func.attr if isinstance(n.func, ast.Attribute) else "")
                        for n in ast.walk(node)
                        if isinstance(n, ast.Call)
                    }
                    - {""}
                )
                symbols.append(
                    {
                        "name": node.name,
                        "kind": "function",
                        "start_line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                        "signature": f"def {node.name}({', '.join(args)})",
                        "docstring": (ast.get_docstring(node) or "")[:240],
                        "calls": calls[:25],
                    }
                )
            elif isinstance(node, ast.ClassDef):
                methods = [
                    m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                symbols.append(
                    {
                        "name": node.name,
                        "kind": "class",
                        "start_line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                        "signature": f"class {node.name} [{', '.join(methods[:8])}]",
                        "docstring": (ast.get_docstring(node) or "")[:240],
                        "calls": methods[:25],
                    }
                )
                for m in node.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        args = [a.arg for a in m.args.args]
                        symbols.append(
                            {
                                "name": f"{node.name}.{m.name}",
                                "kind": "method",
                                "start_line": m.lineno,
                                "end_line": getattr(m, "end_lineno", m.lineno),
                                "signature": f"def {m.name}({', '.join(args)})",
                                "docstring": (ast.get_docstring(m) or "")[:180],
                                "calls": [],
                            }
                        )
        return symbols, imports

    @staticmethod
    def _extract_generic_structure(ext: str, text: str) -> tuple[list[dict], list[dict]]:
        symbols: list[dict] = []
        imports: list[dict] = []
        lines = text.splitlines()
        if ext in {".js", ".ts", ".tsx", ".jsx"}:
            for idx, ln in enumerate(lines, 1):
                m = _JS_SYMBOL_RE.match(ln)
                if m:
                    name = next(g for g in m.groups() if g)
                    symbols.append(
                        {
                            "name": name,
                            "kind": "symbol",
                            "start_line": idx,
                            "end_line": idx,
                            "signature": ln.strip()[:120],
                            "docstring": "",
                            "calls": [],
                        }
                    )
                for im in _JS_IMPORT_RE.finditer(ln):
                    mod = im.group(1) or im.group(2)
                    if mod:
                        imports.append({"module": mod, "names": ""})
        elif ext == ".md":
            for idx, ln in enumerate(lines, 1):
                m = _MD_HEADING_RE.match(ln)
                if m:
                    symbols.append(
                        {
                            "name": m.group(2).strip()[:100],
                            "kind": f"heading_h{len(m.group(1))}",
                            "start_line": idx,
                            "end_line": idx,
                            "signature": ln.strip()[:120],
                            "docstring": "",
                            "calls": [],
                        }
                    )
        return symbols, imports

    def index_project(self, project_path: Path | str) -> dict:
        """
        Indexa incrementalmente un repositorio omitiendo node_modules, binarios y artefactos.
        Solo re-analiza archivos nuevos, modificados o eliminados.
        """
        root = Path(project_path).resolve()
        if not root.is_dir():
            return {"ok": False, "error": f"Directorio de proyecto inválido: {root}"}

        norm_proj = str(root)
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        disk_files: dict[str, Path] = {}

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
            for fname in filenames:
                fpath = Path(dirpath) / fname
                if fpath.suffix.lower() not in INDEXABLE_EXTENSIONS:
                    continue
                try:
                    if fpath.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                rel = str(fpath.relative_to(root))
                disk_files[rel] = fpath

        with self._connect() as conn:
            existing_rows = {
                r["rel_path"]: r["mtime_ns"]
                for r in conn.execute(
                    "SELECT rel_path, mtime_ns FROM indexed_files WHERE project_path = ?",
                    (norm_proj,),
                ).fetchall()
            }

            removed = [rp for rp in existing_rows if rp not in disk_files]
            for rp in removed:
                conn.execute("DELETE FROM indexed_files WHERE project_path = ? AND rel_path = ?", (norm_proj, rp))
                conn.execute("DELETE FROM symbols WHERE project_path = ? AND rel_path = ?", (norm_proj, rp))
                conn.execute("DELETE FROM imports WHERE project_path = ? AND rel_path = ?", (norm_proj, rp))
                conn.execute("DELETE FROM project_fts WHERE project_path = ? AND rel_path = ?", (norm_proj, rp))

            reindexed = 0
            unchanged = 0
            for rel, fpath in disk_files.items():
                try:
                    st = fpath.stat()
                except OSError:
                    continue
                if existing_rows.get(rel) == st.st_mtime_ns:
                    unchanged += 1
                    continue

                text = fpath.read_text(encoding="utf-8", errors="replace")
                ext = fpath.suffix.lower()
                is_test = 1 if self._is_test_file(rel) else 0
                sha = _file_sha256(fpath)

                if ext == ".py":
                    syms, imps = self._extract_python_structure(text)
                else:
                    syms, imps = self._extract_generic_structure(ext, text)

                conn.execute(
                    """
                    INSERT OR REPLACE INTO indexed_files
                    (project_path, rel_path, ext, mtime_ns, sha256, is_test, line_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (norm_proj, rel, ext, st.st_mtime_ns, sha, is_test, len(text.splitlines()), now_iso),
                )
                conn.execute("DELETE FROM symbols WHERE project_path = ? AND rel_path = ?", (norm_proj, rel))
                conn.execute("DELETE FROM imports WHERE project_path = ? AND rel_path = ?", (norm_proj, rel))
                conn.execute("DELETE FROM project_fts WHERE project_path = ? AND rel_path = ?", (norm_proj, rel))

                for s in syms:
                    conn.execute(
                        """
                        INSERT INTO symbols
                        (project_path, rel_path, name, kind, start_line, end_line, signature, docstring, calls_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            norm_proj,
                            rel,
                            s["name"],
                            s["kind"],
                            s["start_line"],
                            s["end_line"],
                            s["signature"],
                            s["docstring"],
                            json.dumps(s["calls"]),
                        ),
                    )
                for imp in imps:
                    conn.execute(
                        "INSERT INTO imports (project_path, rel_path, module_name, imported_names) VALUES (?, ?, ?, ?)",
                        (norm_proj, rel, imp["module"], imp["names"]),
                    )

                sym_names = " ".join(s["name"] for s in syms)
                doc_snips = " ".join(s["docstring"] for s in syms if s["docstring"])
                conn.execute(
                    "INSERT INTO project_fts (project_path, rel_path, symbols_text, summary_text) VALUES (?, ?, ?, ?)",
                    (norm_proj, rel, sym_names, f"{rel} {doc_snips}"[:1500]),
                )
                reindexed += 1

            conn.commit()

        return {
            "ok": True,
            "project_path": norm_proj,
            "total_files": len(disk_files),
            "reindexed": reindexed,
            "unchanged": unchanged,
            "removed": len(removed),
        }

    def find_symbol(self, symbol_query: str, project_path: Path | str, limit: int = 12) -> list[dict]:
        """Responde: ¿Dónde está implementada esta funcionalidad y cómo funciona internamente?"""
        norm_proj = str(Path(project_path).resolve())
        q = f"%{symbol_query.strip()}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT rel_path, name, kind, start_line, end_line, signature, docstring, calls_json
                FROM symbols
                WHERE project_path = ? AND (name LIKE ? OR docstring LIKE ?)
                ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END, start_line ASC
                LIMIT ?
                """,
                (norm_proj, q, q, symbol_query.strip(), limit),
            ).fetchall()
        return [
            {
                "rel_path": r["rel_path"],
                "name": r["name"],
                "kind": r["kind"],
                "start_line": r["start_line"],
                "end_line": r["end_line"],
                "signature": r["signature"],
                "docstring": r["docstring"],
                "calls": json.loads(r["calls_json"] or "[]"),
            }
            for r in rows
        ]

    def get_impact_and_tests(self, target_file_or_symbol: str, project_path: Path | str) -> dict:
        """
        Responde: ¿Qué componentes dependen de ella, qué archivos pueden verse afectados y qué pruebas deben ejecutarse?
        """
        norm_proj = str(Path(project_path).resolve())
        target = target_file_or_symbol.strip()
        stem = Path(target).stem
        mod_hint = target.replace("/", ".").removesuffix(".py")

        with self._connect() as conn:
            # Dependientes por imports
            dep_rows = conn.execute(
                """
                SELECT DISTINCT rel_path, module_name, imported_names
                FROM imports
                WHERE project_path = ? AND (module_name LIKE ? OR imported_names LIKE ?)
                """,
                (norm_proj, f"%{stem}%", f"%{stem}%"),
            ).fetchall()

            # Dependientes por llamadas a símbolos
            call_rows = conn.execute(
                """
                SELECT DISTINCT rel_path, name
                FROM symbols
                WHERE project_path = ? AND calls_json LIKE ?
                """,
                (norm_proj, f"%{stem}%"),
            ).fetchall()

            test_rows = conn.execute(
                "SELECT rel_path FROM indexed_files WHERE project_path = ? AND is_test = 1",
                (norm_proj,),
            ).fetchall()

        dependent_files = sorted(
            {r["rel_path"] for r in dep_rows if r["rel_path"] != target}
            | {r["rel_path"] for r in call_rows if r["rel_path"] != target}
        )
        all_tests = [r["rel_path"] for r in test_rows]
        related_tests = [
            t
            for t in all_tests
            if t in dependent_files or stem.lower() in t.lower() or mod_hint.split(".")[-1].lower() in t.lower()
        ]
        if not related_tests:
            related_tests = all_tests[:6]

        decisions: list[dict] = []
        past_errors: list[dict] = []
        if self.memory is not None:
            mem_query = f"{target} {stem}".strip()
            decisions = self.memory.retrieve_relevant_memories(
                query=mem_query, project_path=norm_proj, tiers=["project"], include_provisional=False, limit=4
            )
            past_errors = [
                m
                for m in self.memory.retrieve_relevant_memories(
                    query=mem_query, project_path=norm_proj, tiers=["experience"], include_provisional=False, limit=6
                )
                if m.get("category") in {"recurring_error", "user_correction"}
            ][:4]

        return {
            "target": target,
            "dependent_files": dependent_files,
            "potentially_affected_files": sorted(set([target] + dependent_files)),
            "related_tests": related_tests,
            "constraining_decisions": [{"id": d["id"], "title": d["title"], "content": d["content"][:200]} for d in decisions],
            "past_errors": [{"id": e["id"], "title": e["title"], "content": e["content"][:200]} for e in past_errors],
        }

    def save_project_state(
        self,
        project_path: Path | str,
        goals: list[str] | None = None,
        architecture_summary: str | None = None,
        completed_features: list[str] | None = None,
        pending_features: list[str] | None = None,
        known_issues: list[str] | None = None,
        decisions: list[str] | None = None,
        test_summary: dict | None = None,
        next_recommended_step: str | None = None,
    ) -> dict:
        """Persiste el estado real de continuidad del proyecto sin confundir tareas mencionadas con terminadas."""
        root = Path(project_path).resolve()
        norm_proj = str(root)
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        git_snap = {
            "branch": _run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"]),
            "head": _run_git(root, ["rev-parse", "--short", "HEAD"]),
            "dirty_files": [ln.strip() for ln in _run_git(root, ["status", "--porcelain"]).splitlines() if ln.strip()][:20],
            "recent_commits": [ln.strip() for ln in _run_git(root, ["log", "-n", "5", "--oneline"]).splitlines() if ln.strip()],
        }

        with self._connect() as conn:
            prev = conn.execute("SELECT * FROM project_continuity WHERE project_path = ?", (norm_proj,)).fetchone()
            merged = {
                "goals": goals if goals is not None else (json.loads(prev["goals_json"]) if prev else []),
                "architecture_summary": architecture_summary if architecture_summary is not None else (prev["architecture_summary"] if prev else ""),
                "completed_features": completed_features if completed_features is not None else (json.loads(prev["completed_features_json"]) if prev else []),
                "pending_features": pending_features if pending_features is not None else (json.loads(prev["pending_features_json"]) if prev else []),
                "known_issues": known_issues if known_issues is not None else (json.loads(prev["known_issues_json"]) if prev else []),
                "decisions": decisions if decisions is not None else (json.loads(prev["decisions_json"]) if prev else []),
                "test_summary": test_summary if test_summary is not None else (json.loads(prev["test_summary_json"]) if prev else {}),
                "next_recommended_step": next_recommended_step if next_recommended_step is not None else (prev["next_recommended_step"] if prev else ""),
            }
            conn.execute(
                """
                INSERT OR REPLACE INTO project_continuity (
                    project_path, goals_json, architecture_summary, completed_features_json,
                    pending_features_json, known_issues_json, decisions_json, test_summary_json,
                    git_snapshot_json, next_recommended_step, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    norm_proj,
                    json.dumps(merged["goals"], ensure_ascii=False),
                    merged["architecture_summary"],
                    json.dumps(merged["completed_features"], ensure_ascii=False),
                    json.dumps(merged["pending_features"], ensure_ascii=False),
                    json.dumps(merged["known_issues"], ensure_ascii=False),
                    json.dumps(merged["decisions"], ensure_ascii=False),
                    json.dumps(merged["test_summary"], ensure_ascii=False),
                    json.dumps(git_snap, ensure_ascii=False),
                    merged["next_recommended_step"],
                    now_iso,
                ),
            )
            conn.commit()
        return {"ok": True, "project_path": norm_proj, "updated_at": now_iso, "git_snapshot": git_snap}

    def reconstruct_continuity_context(self, project_path: Path | str) -> dict:
        """Reconstruye el estado real del proyecto para retomar el trabajo tras días o semanas."""
        root = Path(project_path).resolve()
        norm_proj = str(root)
        idx_stats = self.index_project(root)

        with self._connect() as conn:
            row = conn.execute("SELECT * FROM project_continuity WHERE project_path = ?", (norm_proj,)).fetchone()
            test_cnt = conn.execute("SELECT COUNT(*) FROM indexed_files WHERE project_path = ? AND is_test = 1", (norm_proj,)).fetchone()[0]
            sym_cnt = conn.execute("SELECT COUNT(*) FROM symbols WHERE project_path = ?", (norm_proj,)).fetchone()[0]

        live_git = {
            "branch": _run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"]),
            "head": _run_git(root, ["rev-parse", "--short", "HEAD"]),
            "dirty_files": [ln.strip() for ln in _run_git(root, ["status", "--porcelain"]).splitlines() if ln.strip()][:20],
            "recent_commits": [ln.strip() for ln in _run_git(root, ["log", "-n", "5", "--oneline"]).splitlines() if ln.strip()],
        }

        if row is None:
            return {
                "ok": True,
                "project_path": norm_proj,
                "has_saved_state": False,
                "index_stats": idx_stats,
                "indexed_symbols": sym_cnt,
                "indexed_tests": test_cnt,
                "live_git": live_git,
                "completed_features": [],
                "pending_features": [],
                "known_issues": [],
                "next_recommended_step": "Inspeccionar pendientes reales y pruebas del repositorio.",
            }

        return {
            "ok": True,
            "project_path": norm_proj,
            "has_saved_state": True,
            "updated_at": row["updated_at"],
            "goals": json.loads(row["goals_json"]),
            "architecture_summary": row["architecture_summary"],
            "completed_features": json.loads(row["completed_features_json"]),
            "pending_features": json.loads(row["pending_features_json"]),
            "known_issues": json.loads(row["known_issues_json"]),
            "decisions": json.loads(row["decisions_json"]),
            "test_summary": json.loads(row["test_summary_json"]),
            "saved_git": json.loads(row["git_snapshot_json"]),
            "live_git": live_git,
            "next_recommended_step": row["next_recommended_step"],
            "index_stats": idx_stats,
            "indexed_symbols": sym_cnt,
            "indexed_tests": test_cnt,
        }
