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
import fnmatch
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
from collections import defaultdict
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
INDEXABLE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".md", ".json", ".jsonc", ".toml",
    ".rs", ".go", ".c", ".cpp", ".h", ".hpp", ".yaml", ".yml",
}
MAX_FILE_BYTES = 512 * 1024
SECRET_FILE_PATTERNS = (".env", ".env.*", "*.key", "*.pem", "*.p12", "*.pfx", "*secret*", "*credentials*")

_JS_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function\s+([A-Za-z_]\w*)|class\s+([A-Za-z_]\w*)|interface\s+([A-Za-z_]\w*)|type\s+([A-Za-z_]\w*)\s*=|const\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?\()"
)
_JS_IMPORT_RE = re.compile(r"""(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\))""")
_RUST_SYMBOL_RE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:fn|struct|enum|trait|impl)\s+([A-Za-z_]\w*)")
_RUST_IMPORT_RE = re.compile(r"^\s*use\s+([A-Za-z0-9_:]+)")
_GO_SYMBOL_RE = re.compile(r"^\s*(?:func\s+(?:\([^)]+\)\s+)?([A-Za-z_]\w*)|type\s+([A-Za-z_]\w*)\s+(?:struct|interface))")
_SH_SYMBOL_RE = re.compile(r"^\s*(?:function\s+([A-Za-z_]\w*)|([A-Za-z_]\w*)\s*\(\s*\)\s*\{)")
_MD_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")


def _normalized_body_hash(lines: list[str]) -> str:
    """Hash estructural normalizado para detectar bloques de código duplicados (>= 6 líneas)."""
    meaningful = [re.sub(r"\s+", " ", ln.strip()) for ln in lines if ln.strip() and not ln.strip().startswith(("#", "//"))]
    if len(meaningful) < 6:
        return ""
    return hashlib.sha256("\n".join(meaningful).encode("utf-8", errors="ignore")).hexdigest()[:16]


def _load_ignore_patterns(root: Path) -> list[str]:
    patterns: list[str] = []
    for fname in (".gitignore", ".saghetignore"):
        p = root / fname
        if p.is_file():
            try:
                for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = raw.strip()
                    if not line or line.startswith("#") or line.startswith("!"):
                        continue
                    patterns.append(line.rstrip("/"))
            except OSError:
                pass
    return patterns


def _is_ignored_rel(rel_path: str, patterns: list[str], is_dir: bool = False) -> bool:
    name = Path(rel_path).name
    if not is_dir:
        for sec_pat in SECRET_FILE_PATTERNS:
            if fnmatch.fnmatch(name.lower(), sec_pat):
                return True
    for pat in patterns:
        clean = pat.lstrip("/")
        if fnmatch.fnmatch(rel_path, clean) or fnmatch.fnmatch(name, clean):
            return True
        if "/" not in clean and any(fnmatch.fnmatch(part, clean) for part in Path(rel_path).parts):
            return True
    return False


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
                    calls_json TEXT NOT NULL DEFAULT '[]',
                    body_hash TEXT NOT NULL DEFAULT ''
                )
                """
            )
            cols = {r[1] for r in conn.execute("PRAGMA table_info(symbols)").fetchall()}
            if "body_hash" not in cols:
                conn.execute("ALTER TABLE symbols ADD COLUMN body_hash TEXT NOT NULL DEFAULT ''")
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

        lines = text.splitlines()
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
                end_ln = getattr(node, "end_lineno", node.lineno)
                symbols.append(
                    {
                        "name": node.name,
                        "kind": "function",
                        "start_line": node.lineno,
                        "end_line": end_ln,
                        "signature": f"def {node.name}({', '.join(args)})",
                        "docstring": (ast.get_docstring(node) or "")[:240],
                        "calls": calls[:25],
                        "body_hash": _normalized_body_hash(lines[node.lineno - 1 : end_ln]),
                    }
                )
            elif isinstance(node, ast.ClassDef):
                methods = [
                    m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                end_ln = getattr(node, "end_lineno", node.lineno)
                symbols.append(
                    {
                        "name": node.name,
                        "kind": "class",
                        "start_line": node.lineno,
                        "end_line": end_ln,
                        "signature": f"class {node.name} [{', '.join(methods[:8])}]",
                        "docstring": (ast.get_docstring(node) or "")[:240],
                        "calls": methods[:25],
                        "body_hash": "",
                    }
                )
                for m in node.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        args = [a.arg for a in m.args.args]
                        m_end = getattr(m, "end_lineno", m.lineno)
                        m_calls = sorted(
                            {
                                n.func.id if isinstance(n.func, ast.Name) else (n.func.attr if isinstance(n.func, ast.Attribute) else "")
                                for n in ast.walk(m)
                                if isinstance(n, ast.Call)
                            }
                            - {""}
                        )
                        symbols.append(
                            {
                                "name": f"{node.name}.{m.name}",
                                "kind": "method",
                                "start_line": m.lineno,
                                "end_line": m_end,
                                "signature": f"def {m.name}({', '.join(args)})",
                                "docstring": (ast.get_docstring(m) or "")[:180],
                                "calls": m_calls[:25],
                                "body_hash": _normalized_body_hash(lines[m.lineno - 1 : m_end]),
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
                    kind = "interface" if "interface " in ln else ("type" if "type " in ln else ("class" if "class " in ln else "function"))
                    symbols.append(
                        {
                            "name": name,
                            "kind": kind,
                            "start_line": idx,
                            "end_line": idx,
                            "signature": ln.strip()[:120],
                            "docstring": "",
                            "calls": [],
                            "body_hash": _normalized_body_hash(lines[idx - 1 : min(len(lines), idx + 10)]),
                        }
                    )
                for im in _JS_IMPORT_RE.finditer(ln):
                    mod = im.group(1) or im.group(2)
                    if mod:
                        imports.append({"module": mod, "names": ""})
        elif ext == ".rs":
            for idx, ln in enumerate(lines, 1):
                m = _RUST_SYMBOL_RE.match(ln)
                if m:
                    symbols.append(
                        {
                            "name": m.group(1),
                            "kind": "rust_symbol",
                            "start_line": idx,
                            "end_line": idx,
                            "signature": ln.strip()[:120],
                            "docstring": "",
                            "calls": [],
                            "body_hash": "",
                        }
                    )
                im = _RUST_IMPORT_RE.match(ln)
                if im:
                    imports.append({"module": im.group(1), "names": ""})
        elif ext == ".go":
            for idx, ln in enumerate(lines, 1):
                m = _GO_SYMBOL_RE.match(ln)
                if m:
                    name = next(g for g in m.groups() if g)
                    symbols.append(
                        {
                            "name": name,
                            "kind": "go_symbol",
                            "start_line": idx,
                            "end_line": idx,
                            "signature": ln.strip()[:120],
                            "docstring": "",
                            "calls": [],
                            "body_hash": "",
                        }
                    )
        elif ext == ".sh":
            for idx, ln in enumerate(lines, 1):
                m = _SH_SYMBOL_RE.match(ln)
                if m:
                    name = next(g for g in m.groups() if g)
                    symbols.append(
                        {
                            "name": name,
                            "kind": "shell_fn",
                            "start_line": idx,
                            "end_line": idx,
                            "signature": ln.strip()[:120],
                            "docstring": "",
                            "calls": [],
                            "body_hash": "",
                        }
                    )
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
                            "body_hash": "",
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
        ignore_patterns = _load_ignore_patterns(root)
        disk_files: dict[str, Path] = {}

        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            kept_dirs = []
            for d in dirnames:
                if d in IGNORED_DIRS or d.startswith("."):
                    continue
                sub_rel = d if rel_dir == "." else f"{rel_dir}/{d}"
                if _is_ignored_rel(sub_rel, ignore_patterns, is_dir=True):
                    continue
                kept_dirs.append(d)
            dirnames[:] = kept_dirs

            for fname in filenames:
                fpath = Path(dirpath) / fname
                if fpath.suffix.lower() not in INDEXABLE_EXTENSIONS:
                    continue
                rel = str(fpath.relative_to(root))
                if _is_ignored_rel(rel, ignore_patterns, is_dir=False):
                    continue
                try:
                    if fpath.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                disk_files[rel] = fpath

        with self._connect() as conn:
            existing_rows = {
                r["rel_path"]: (r["mtime_ns"], r["sha256"])
                for r in conn.execute(
                    "SELECT rel_path, mtime_ns, sha256 FROM indexed_files WHERE project_path = ?",
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
                prev_meta = existing_rows.get(rel)
                if prev_meta and prev_meta[0] == st.st_mtime_ns:
                    unchanged += 1
                    continue

                sha = _file_sha256(fpath)
                if prev_meta and prev_meta[1] == sha:
                    # Content-addressable cache hit: mtime changed (e.g. git checkout), content identical
                    conn.execute(
                        "UPDATE indexed_files SET mtime_ns = ?, updated_at = ? WHERE project_path = ? AND rel_path = ?",
                        (st.st_mtime_ns, now_iso, norm_proj, rel),
                    )
                    unchanged += 1
                    continue

                text = fpath.read_text(encoding="utf-8", errors="replace")
                ext = fpath.suffix.lower()
                is_test = 1 if self._is_test_file(rel) else 0

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
                        (project_path, rel_path, name, kind, start_line, end_line, signature, docstring, calls_json, body_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                            s.get("body_hash", ""),
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

    def _build_internal_graph(self, conn: sqlite3.Connection, norm_proj: str) -> tuple[list[str], dict[str, set[str]]]:
        """Construye grafo dirigido de dependencias internas (archivo -> archivos importados)."""
        files = [
            r["rel_path"]
            for r in conn.execute("SELECT rel_path FROM indexed_files WHERE project_path = ?", (norm_proj,)).fetchall()
        ]
        stem_to_files: dict[str, list[str]] = defaultdict(list)
        mod_to_file: dict[str, str] = {}
        for rp in files:
            p = Path(rp)
            stem_to_files[p.stem].append(rp)
            mod_name = rp.replace("/", ".").removesuffix(p.suffix)
            mod_to_file[mod_name] = rp
            if mod_name.endswith(".__init__"):
                mod_to_file[mod_name.removesuffix(".__init__")] = rp

        adj: dict[str, set[str]] = {rp: set() for rp in files}
        imp_rows = conn.execute("SELECT rel_path, module_name FROM imports WHERE project_path = ?", (norm_proj,)).fetchall()
        for r in imp_rows:
            src = r["rel_path"]
            mod = (r["module_name"] or "").strip()
            if not mod or src not in adj:
                continue
            if mod in mod_to_file and mod_to_file[mod] != src:
                adj[src].add(mod_to_file[mod])
                continue
            clean = mod.lstrip("./").replace("/", ".")
            if clean in mod_to_file and mod_to_file[clean] != src:
                adj[src].add(mod_to_file[clean])
                continue
            last = clean.split(".")[-1]
            for cand in stem_to_files.get(last, []):
                if cand != src and len(stem_to_files[last]) == 1:
                    adj[src].add(cand)
        return files, adj

    def detect_circular_dependencies(self, project_path: Path | str) -> list[list[str]]:
        """Detecta ciclos en el grafo de dependencias internas entre archivos."""
        norm_proj = str(Path(project_path).resolve())
        with self._connect() as conn:
            files, adj = self._build_internal_graph(conn, norm_proj)

        state: dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=done
        stack: list[str] = []
        cycles: list[list[str]] = []
        seen_sigs: set[tuple[str, ...]] = set()

        def _dfs(u: str) -> None:
            state[u] = 1
            stack.append(u)
            for v in sorted(adj.get(u, ())):
                st = state.get(v, 0)
                if st == 1:
                    idx = stack.index(v)
                    cyc = stack[idx:] + [v]
                    sig = tuple(sorted(set(cyc)))
                    if sig not in seen_sigs:
                        seen_sigs.add(sig)
                        cycles.append(cyc)
                elif st == 0:
                    _dfs(v)
            stack.pop()
            state[u] = 2

        for f in sorted(files):
            if state.get(f, 0) == 0:
                _dfs(f)
        return cycles[:20]

    def detect_duplicate_code(self, project_path: Path | str) -> list[dict]:
        """Detecta funciones o métodos con cuerpo estructuralmente idéntico (>= 6 líneas)."""
        norm_proj = str(Path(project_path).resolve())
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT body_hash, rel_path, name, start_line, end_line
                FROM symbols
                WHERE project_path = ? AND body_hash != ''
                """,
                (norm_proj,),
            ).fetchall()
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            groups[r["body_hash"]].append(
                {
                    "rel_path": r["rel_path"],
                    "name": r["name"],
                    "lines": f"{r['start_line']}-{r['end_line']}",
                }
            )
        return [
            {"body_hash": bh, "occurrences": occ}
            for bh, occ in groups.items()
            if len(occ) >= 2
        ][:20]

    def detect_entry_points(self, project_path: Path | str) -> list[dict]:
        """Identifica puntos de entrada (main, CLI, servidores, scripts ejecutables)."""
        norm_proj = str(Path(project_path).resolve())
        entries: list[dict] = []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT f.rel_path, f.ext, GROUP_CONCAT(s.name, ',') AS syms
                FROM indexed_files f
                LEFT JOIN symbols s ON s.project_path = f.project_path AND s.rel_path = f.rel_path
                WHERE f.project_path = ? AND f.is_test = 0
                GROUP BY f.rel_path
                """,
                (norm_proj,),
            ).fetchall()
        for r in rows:
            rp = r["rel_path"]
            syms = (r["syms"] or "").split(",")
            name = Path(rp).name.lower()
            reasons: list[str] = []
            if "main" in syms:
                reasons.append("defines_main")
            if name in {"server.py", "app.py", "cli.py", "main.py", "index.ts", "index.js", "install.sh", "doctor.sh"}:
                reasons.append("entrypoint_filename")
            if reasons:
                entries.append({"rel_path": rp, "reasons": reasons})
        return entries[:25]

    def search_hybrid(self, query: str, project_path: Path | str, limit: int = 12) -> list[dict]:
        """Búsqueda híbrida: FTS5 BM25 sobre project_fts + coincidencia estructural en symbols."""
        norm_proj = str(Path(project_path).resolve())
        tokens = [t for t in re.findall(r"[A-Za-z0-9_]{2,}", query or "") if len(t) >= 2][:8]
        if not tokens:
            return []

        scores: dict[str, float] = defaultdict(float)
        reasons: dict[str, list[str]] = defaultdict(list)

        with self._connect() as conn:
            fts_query = " OR ".join(f'"{t}"' for t in tokens)
            try:
                fts_rows = conn.execute(
                    """
                    SELECT rel_path, bm25(project_fts) AS rank
                    FROM project_fts
                    WHERE project_path = ? AND project_fts MATCH ?
                    ORDER BY rank ASC
                    LIMIT ?
                    """,
                    (norm_proj, fts_query, limit * 2),
                ).fetchall()
                for r in fts_rows:
                    scores[r["rel_path"]] += max(0.2, 2.0 - min(1.8, abs(float(r["rank"]))))
                    reasons[r["rel_path"]].append("fts_bm25")
            except sqlite3.OperationalError:
                pass

            for tok in tokens:
                sym_rows = conn.execute(
                    """
                    SELECT DISTINCT rel_path, name
                    FROM symbols
                    WHERE project_path = ? AND name LIKE ?
                    LIMIT ?
                    """,
                    (norm_proj, f"%{tok}%", limit),
                ).fetchall()
                for r in sym_rows:
                    exact_bonus = 2.5 if r["name"].lower() == tok.lower() else 1.2
                    scores[r["rel_path"]] += exact_bonus
                    reasons[r["rel_path"]].append(f"symbol:{r['name']}")

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        return [
            {"rel_path": rp, "score": round(sc, 3), "matched": sorted(set(reasons[rp]))[:5]}
            for rp, sc in ranked
        ]

    def build_repo_map(
        self,
        project_path: Path | str,
        max_files: int = 25,
        max_chars: int = 4000,
    ) -> dict:
        """
        Construye un mapa estructural estilo Aider (PageRank sobre grafo de dependencias),
        detectando módulos críticos, puntos de entrada, ciclos y código duplicado.
        """
        root = Path(project_path).resolve()
        norm_proj = str(root)
        with self._connect() as conn:
            files, adj = self._build_internal_graph(conn, norm_proj)
            sym_rows = conn.execute(
                """
                SELECT rel_path, name, kind, signature, start_line
                FROM symbols
                WHERE project_path = ? AND kind IN ('class', 'function', 'interface', 'type', 'rust_symbol', 'go_symbol', 'shell_fn')
                ORDER BY rel_path, start_line
                """,
                (norm_proj,),
            ).fetchall()

        n = len(files)
        ranks = {f: 1.0 / max(1, n) for f in files}
        in_degree: dict[str, int] = {f: 0 for f in files}
        for src, targets in adj.items():
            for tgt in targets:
                in_degree[tgt] = in_degree.get(tgt, 0) + 1

        # PageRank (15 iteraciones)
        damping = 0.85
        for _ in range(15):
            new_ranks = {f: (1.0 - damping) / max(1, n) for f in files}
            for src, targets in adj.items():
                if targets:
                    share = damping * ranks[src] / len(targets)
                    for tgt in targets:
                        new_ranks[tgt] += share
                else:
                    share = damping * ranks[src] / max(1, n)
                    for f in files:
                        new_ranks[f] += share
            ranks = new_ranks

        ranked_files = sorted(files, key=lambda f: (ranks.get(f, 0.0), in_degree.get(f, 0)), reverse=True)
        syms_by_file: dict[str, list[str]] = defaultdict(list)
        for r in sym_rows:
            syms_by_file[r["rel_path"]].append(f"{r['signature']} (L{r['start_line']})")

        lines: list[str] = []
        used = 0
        for rp in ranked_files[:max_files]:
            sigs = syms_by_file.get(rp, [])[:6]
            entry = f"{rp} [rank={ranks[rp]:.3f}, in={in_degree[rp]}]: " + (", ".join(sigs) if sigs else "(module)")
            if used + len(entry) + 1 > max_chars:
                break
            lines.append(entry)
            used += len(entry) + 1

        cycles = self.detect_circular_dependencies(root)
        duplicates = self.detect_duplicate_code(root)
        entry_points = self.detect_entry_points(root)
        critical_modules = [
            {"rel_path": f, "pagerank": round(ranks[f], 4), "in_degree": in_degree[f]}
            for f in ranked_files[:8]
            if in_degree[f] > 0 or ranks[f] > (1.0 / max(1, n))
        ]

        return {
            "ok": True,
            "project_path": norm_proj,
            "total_files": n,
            "critical_modules": critical_modules,
            "entry_points": entry_points,
            "circular_dependencies": cycles,
            "duplicate_blocks_count": len(duplicates),
            "duplicate_blocks": duplicates[:10],
            "repo_map_text": "\n".join(lines),
        }

    def trace_execution_paths(self, target: str, project_path: Path | str, max_depth: int = 4) -> dict:
        """Traza rutas de dependencias/llamadas entrantes y salientes para un archivo o símbolo."""
        norm_proj = str(Path(project_path).resolve())
        with self._connect() as conn:
            files, adj = self._build_internal_graph(conn, norm_proj)
        rev_adj: dict[str, set[str]] = {f: set() for f in files}
        for src, targets in adj.items():
            for tgt in targets:
                rev_adj.setdefault(tgt, set()).add(src)

        matched = [f for f in files if target in f]
        if not matched:
            syms = self.find_symbol(target, norm_proj, limit=5)
            matched = sorted({s["rel_path"] for s in syms})
        if not matched:
            return {"target": target, "matched_files": [], "downstream": [], "upstream": []}

        def _bfs(start_nodes: list[str], graph: dict[str, set[str]]) -> list[str]:
            visited = set(start_nodes)
            frontier = list(start_nodes)
            order: list[str] = []
            for _ in range(max_depth):
                next_f: list[str] = []
                for u in frontier:
                    for v in sorted(graph.get(u, ())):
                        if v not in visited:
                            visited.add(v)
                            order.append(v)
                            next_f.append(v)
                frontier = next_f
                if not frontier:
                    break
            return order

        return {
            "target": target,
            "matched_files": matched,
            "downstream_dependencies": _bfs(matched, adj),
            "upstream_callers": _bfs(matched, rev_adj),
        }

    def select_relevant_context(
        self,
        objective: str,
        project_path: Path | str,
        max_chars: int = 3200,
    ) -> dict:
        """
        Selecciona los fragmentos estructurales más relevantes para un objetivo sin saturar la ventana de contexto.
        Combina búsqueda híbrida (FTS5 + símbolos) + análisis de impacto + mapa crítico.
        """
        root = Path(project_path).resolve()
        hits = self.search_hybrid(objective, root, limit=8)
        selected_files = [h["rel_path"] for h in hits]
        impact = self.get_impact_and_tests(selected_files[0], root) if selected_files else {}

        repo_map = self.build_repo_map(root, max_files=12, max_chars=max(600, max_chars // 2))
        sections: list[str] = []
        if hits:
            sections.append("[RELEVANT_FILES] " + ", ".join(f"{h['rel_path']}({h['score']})" for h in hits[:6]))
        if impact.get("related_tests"):
            sections.append("[RELATED_TESTS] " + ", ".join(impact["related_tests"][:5]))
        if repo_map.get("repo_map_text"):
            sections.append("[REPO_MAP]\n" + repo_map["repo_map_text"])

        context_text = "\n".join(sections)[:max_chars]
        return {
            "ok": True,
            "relevant_files": hits,
            "related_tests": impact.get("related_tests", []),
            "dependent_files": impact.get("dependent_files", []),
            "critical_modules": repo_map.get("critical_modules", [])[:5],
            "context_text": context_text,
        }
