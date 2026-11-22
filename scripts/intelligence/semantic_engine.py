#!/usr/bin/env python3
"""
Semantic Project Understanding Engine — OpenCode-Saghet (Fase 2 / v0.5.0).

Extiende `ProjectIntelligenceEngine` (reutilizando su caché incremental SQLite mtime+sha256,
FTS5 BM25, PageRank, detección de ciclos y duplicados) para construir comprensión semántica
profunda inspirada en Aider RepoMap, Tree-sitter, OpenHands, SWE-agent y Continue:

A. Codebase Intelligence:
   - Detección de lenguajes y frameworks reales (manifests + imports).
   - Módulos, clases, funciones, análisis de llamadas y dependencias externas/internas.
   - Interfaces públicas, contratos (rutas API, comandos CLI, firmas tipadas).
   - Clasificación de lógica de negocio vs interfaz (CLI/UI/API/Infraestructura).
   - Reconocimiento de componentes reutilizables desacoplados.
B. Repository Graph:
   - Grafo estructurado de archivos, funciones, clases, servicios, dependencias,
     relaciones entre módulos, flujos de ejecución, entradas/salidas y contratos.
C. Context Intelligence:
   - Recuperación previa a modificar código: archivos relacionados, dependencias afectadas,
     funciones consumidoras, pruebas existentes y decisiones arquitectónicas previas.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from collections import defaultdict
from pathlib import Path

from scripts.memory.hierarchical_memory import HierarchicalMemoryStore
from scripts.memory.project_intelligence import ProjectIntelligenceEngine

_LANG_BY_EXT: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".rs": "Rust",
    ".go": "Go",
    ".sh": "Shell",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++",
    ".hpp": "C++",
    ".html": "HTML",
    ".css": "CSS",
    ".sql": "SQL",
    ".json": "JSON",
    ".toml": "TOML",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".md": "Markdown",
}

_ROUTE_RE = re.compile(
    r"""(?:@(?:app|router|bp)\.(get|post|put|patch|delete|websocket)\(\s*['"]([^'"]+)['"]|"""
    r"""(?:app|router)\.(get|post|put|patch|delete)\(\s*['"]([^'"]+)['"]|"""
    r"""parsed\.path\s*==\s*['"](/api/[^'"]+)['"])""",
    re.IGNORECASE,
)
_CLI_PATTERNS = re.compile(
    r"\b(argparse|ArgumentParser|add_subparsers|click\.command|click\.group|typer\.Typer|commander|yargs|clap::Parser|cobra\.Command|sys\.argv)\b"
)
_UI_PATTERNS = re.compile(
    r"\b(React|useState|useEffect|createRoot|document\.getElementById|PyQt6|PySide6|tkinter|ttk|QMainWindow|QApplication|tauri|electron|svelte|Vue|@Component)\b"
)
_INFRA_PATTERNS = re.compile(
    r"\b(sqlite3|psycopg|sqlalchemy|redis|valkey|subprocess\.run|urllib\.request|httpx|aiohttp|requests\.|socket\.|open\(|shutil\.)\b"
)
_SERVICE_CLASS_RE = re.compile(r"(Service|Engine|Manager|Coordinator|Controller|Repository|Store|Client|Adapter|Supervisor|Planner|Router)$")


def detect_tree_sitter_support() -> dict:
    """Detecta si el entorno dispone de bindings Tree-sitter reales sin fallar si faltan."""
    has_ts = importlib.util.find_spec("tree_sitter") is not None
    has_pack = importlib.util.find_spec("tree_sitter_language_pack") is not None
    has_langs = importlib.util.find_spec("tree_sitter_languages") is not None
    grammars = [
        lang
        for lang in ("python", "javascript", "typescript", "rust", "go", "bash")
        if importlib.util.find_spec(f"tree_sitter_{lang}") is not None
    ]
    return {
        "tree_sitter_available": bool(has_ts and (has_pack or has_langs or grammars)),
        "tree_sitter_core": has_ts,
        "language_pack": has_pack or has_langs,
        "installed_grammars": grammars,
        "active_backend": "tree_sitter+ast" if (has_ts and (has_pack or has_langs or grammars)) else "python_ast+structural_parser",
    }


def _extract_python_io_and_contracts(text: str, rel_path: str) -> dict:
    """Extrae firmas tipadas (entradas/salidas), interfaces públicas, rutas y servicios desde AST Python."""
    public_interfaces: list[dict] = []
    services: list[dict] = []
    inputs_outputs: list[dict] = []
    call_edges: list[dict] = []
    explicit_all: set[str] | None = None

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {
            "public_interfaces": public_interfaces,
            "services": services,
            "inputs_outputs": inputs_outputs,
            "call_edges": call_edges,
        }

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple)):
                    explicit_all = {
                        elt.value for elt in node.value.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    }

    def _ann_str(ann: ast.AST | None) -> str:
        if ann is None:
            return "Any"
        try:
            return ast.unparse(ann)[:60]
        except Exception:
            return "Any"

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_public = (node.name in explicit_all) if explicit_all is not None else (not node.name.startswith("_"))
            params = [{"name": a.arg, "type": _ann_str(a.annotation)} for a in node.args.args]
            ret_type = _ann_str(node.returns)
            io_entry = {
                "file": rel_path,
                "symbol": node.name,
                "kind": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                "inputs": params,
                "output": ret_type,
                "line": node.lineno,
            }
            inputs_outputs.append(io_entry)
            if is_public:
                public_interfaces.append(io_entry)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    callee = (
                        sub.func.id
                        if isinstance(sub.func, ast.Name)
                        else (sub.func.attr if isinstance(sub.func, ast.Attribute) else "")
                    )
                    if callee and callee != node.name:
                        call_edges.append({"caller_file": rel_path, "caller": node.name, "callee": callee})

        elif isinstance(node, ast.ClassDef):
            is_public = (node.name in explicit_all) if explicit_all is not None else (not node.name.startswith("_"))
            methods: list[dict] = []
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    params = [{"name": a.arg, "type": _ann_str(a.annotation)} for a in m.args.args if a.arg != "self"]
                    ret_type = _ann_str(m.returns)
                    if not m.name.startswith("_") or m.name == "__init__":
                        methods.append({"name": m.name, "inputs": params, "output": ret_type, "line": m.lineno})
                    for sub in ast.walk(m):
                        if isinstance(sub, ast.Call):
                            callee = (
                                sub.func.id
                                if isinstance(sub.func, ast.Name)
                                else (sub.func.attr if isinstance(sub.func, ast.Attribute) else "")
                            )
                            if callee and callee != m.name:
                                call_edges.append({"caller_file": rel_path, "caller": f"{node.name}.{m.name}", "callee": callee})
            if is_public:
                public_interfaces.append(
                    {
                        "file": rel_path,
                        "symbol": node.name,
                        "kind": "class",
                        "methods": [m["name"] for m in methods[:12]],
                        "line": node.lineno,
                    }
                )
            if _SERVICE_CLASS_RE.search(node.name) or len(methods) >= 3:
                services.append(
                    {
                        "name": node.name,
                        "file": rel_path,
                        "line": node.lineno,
                        "public_methods": [m["name"] for m in methods if not m["name"].startswith("_")][:12],
                    }
                )

    return {
        "public_interfaces": public_interfaces,
        "services": services,
        "inputs_outputs": inputs_outputs,
        "call_edges": call_edges,
    }


class SemanticProjectEngine:
    """
    Motor de Comprensión Semántica de Proyectos (Fase 2).
    Reutiliza `ProjectIntelligenceEngine` (caché incremental SQLite + FTS5 + PageRank)
    y construye Codebase Intelligence, Repository Graph y Context Intelligence.
    """

    def __init__(
        self,
        project_engine: ProjectIntelligenceEngine | None = None,
        db_path: Path | None = None,
        memory_store: HierarchicalMemoryStore | None = None,
    ) -> None:
        self.memory = memory_store
        self.pi = project_engine or ProjectIntelligenceEngine(db_path=db_path, memory_store=memory_store)
        self.ts_info = detect_tree_sitter_support()

    def detect_languages_and_frameworks(self, project_path: Path | str) -> dict:
        """Detecta lenguajes por volumen/archivos y frameworks reales a partir de manifiestos e imports."""
        root = Path(project_path).resolve()
        norm_proj = str(root)
        self.pi.index_project(root)

        lang_counts: dict[str, int] = defaultdict(int)
        lang_lines: dict[str, int] = defaultdict(int)
        frameworks: set[str] = set()
        external_deps: dict[str, list[str]] = defaultdict(list)

        with self.pi._connect() as conn:
            file_rows = conn.execute(
                "SELECT rel_path, ext, line_count FROM indexed_files WHERE project_path = ?",
                (norm_proj,),
            ).fetchall()
            imp_rows = conn.execute(
                "SELECT DISTINCT module_name FROM imports WHERE project_path = ?",
                (norm_proj,),
            ).fetchall()

        for r in file_rows:
            lang = _LANG_BY_EXT.get(r["ext"].lower(), r["ext"].lstrip(".").upper() or "Other")
            lang_counts[lang] += 1
            lang_lines[lang] += int(r["line_count"] or 0)

        imported_mods = {str(r["module_name"] or "").split(".")[0].lower() for r in imp_rows}
        imp_fw_map = {
            "fastapi": "FastAPI",
            "flask": "Flask",
            "django": "Django",
            "click": "Click (CLI)",
            "typer": "Typer (CLI)",
            "argparse": "Argparse (CLI)",
            "pyqt6": "PyQt6 (Desktop)",
            "pyside6": "PySide6 (Desktop)",
            "tkinter": "Tkinter (Desktop)",
            "pytest": "pytest",
            "unittest": "unittest",
            "react": "React",
            "next": "Next.js",
            "vue": "Vue",
            "svelte": "Svelte",
            "express": "Express",
            "@nestjs/core": "NestJS",
            "electron": "Electron",
            "@tauri-apps/api": "Tauri",
            "commander": "Commander (CLI)",
        }
        for mod, fw in imp_fw_map.items():
            if mod in imported_mods:
                frameworks.add(fw)

        # Manifiestos reales del proyecto
        pkg_json = root / "package.json"
        if pkg_json.is_file():
            try:
                pkg = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
                all_js_deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
                external_deps["npm"] = sorted(all_js_deps.keys())[:40]
                for dep_k, fw_name in (
                    ("react", "React"),
                    ("next", "Next.js"),
                    ("vue", "Vue"),
                    ("svelte", "Svelte"),
                    ("@angular/core", "Angular"),
                    ("vite", "Vite"),
                    ("electron", "Electron"),
                    ("@tauri-apps/api", "Tauri"),
                    ("@nestjs/core", "NestJS"),
                    ("express", "Express"),
                    ("react-native", "React Native"),
                    ("commander", "Commander (CLI)"),
                ):
                    if dep_k in all_js_deps:
                        frameworks.add(fw_name)
            except Exception:
                pass

        req_txt = root / "requirements.txt"
        if req_txt.is_file():
            deps = []
            for ln in req_txt.read_text(encoding="utf-8", errors="replace").splitlines():
                clean = ln.split("#")[0].strip()
                if clean:
                    pkg_name = re.split(r"[=<>!~\[]", clean)[0].strip().lower()
                    if pkg_name:
                        deps.append(pkg_name)
            external_deps["python"] = sorted(set(deps))[:40]
            for d in deps:
                if d in imp_fw_map:
                    frameworks.add(imp_fw_map[d])

        pyproj = root / "pyproject.toml"
        if pyproj.is_file():
            txt = pyproj.read_text(encoding="utf-8", errors="replace")
            for k, fw in (("fastapi", "FastAPI"), ("flask", "Flask"), ("django", "Django"), ("typer", "Typer (CLI)"), ("click", "Click (CLI)"), ("pytest", "pytest")):
                if re.search(rf"\b{k}\b", txt, re.IGNORECASE):
                    frameworks.add(fw)

        cargo = root / "Cargo.toml"
        if cargo.is_file():
            txt = cargo.read_text(encoding="utf-8", errors="replace")
            for k, fw in (("tauri", "Tauri"), ("actix-web", "Actix"), ("axum", "Axum"), ("clap", "Clap (CLI)")):
                if k in txt:
                    frameworks.add(fw)

        if (root / "pubspec.yaml").is_file():
            frameworks.add("Flutter")
        if (root / "go.mod").is_file():
            txt = (root / "go.mod").read_text(encoding="utf-8", errors="replace")
            for k, fw in (("gin-gonic", "Gin"), ("gofiber", "Fiber"), ("spf13/cobra", "Cobra (CLI)")):
                if k in txt:
                    frameworks.add(fw)

        ordered_langs = [
            {"language": lang, "files": cnt, "lines": lang_lines[lang]}
            for lang, cnt in sorted(lang_counts.items(), key=lambda kv: (kv[1], lang_lines[kv[0]]), reverse=True)
        ]
        return {
            "languages": ordered_langs,
            "primary_language": ordered_langs[0]["language"] if ordered_langs else "Unknown",
            "frameworks": sorted(frameworks),
            "external_dependencies": dict(external_deps),
        }

    @staticmethod
    def classify_file_layer(rel_path: str, text: str, is_test: bool) -> dict:
        """Clasifica un archivo en su capa arquitectónica y separa lógica de negocio de interfaz."""
        low = rel_path.lower()
        if is_test:
            return {"layer": "test", "has_business_logic": False, "has_cli": False, "has_ui": False}
        if low.endswith((".md", ".json", ".jsonc", ".toml", ".yaml", ".yml")) or "/config/" in f"/{low}":
            return {"layer": "config_or_docs", "has_business_logic": False, "has_cli": False, "has_ui": False}

        has_cli = bool(_CLI_PATTERNS.search(text)) or ("if __name__ ==" in text and "argparse" in text)
        has_ui = bool(_UI_PATTERNS.search(text)) or low.endswith((".html", ".css", ".tsx", ".jsx", ".vue", ".svelte"))
        has_api = bool(_ROUTE_RE.search(text)) or "http.server" in text or "BaseHTTPRequestHandler" in text
        has_infra = bool(_INFRA_PATTERNS.search(text))

        if has_ui and not has_api:
            layer = "presentation_ui"
        elif has_api:
            layer = "api_layer"
        elif has_cli and not any(k in low for k in ("domain", "core", "service", "model", "engine")):
            layer = "cli_interface"
        elif any(k in low for k in ("domain", "core", "rules", "calc", "logic", "model")):
            layer = "domain_business_logic"
        elif any(k in low for k in ("service", "usecase", "application", "engine", "planner", "supervisor")):
            layer = "application_service"
        elif has_infra:
            layer = "infrastructure"
        else:
            layer = "domain_business_logic"

        has_business = layer in {"domain_business_logic", "application_service"} or (has_cli and ("def " in text))
        return {
            "layer": layer,
            "has_business_logic": has_business,
            "has_cli": has_cli,
            "has_ui": has_ui,
            "has_api": has_api,
            "has_infra": has_infra,
        }

    def analyze_codebase(self, project_path: Path | str) -> dict:
        """
        Ejecuta análisis completo (A. Codebase Intelligence + B. Repository Graph) con caché incremental.
        """
        root = Path(project_path).resolve()
        norm_proj = str(root)
        idx_stats = self.pi.index_project(root)
        if not idx_stats.get("ok"):
            return idx_stats

        lang_fw = self.detect_languages_and_frameworks(root)
        repo_map = self.pi.build_repo_map(root, max_files=30, max_chars=4500)

        with self.pi._connect() as conn:
            files_list, adj = self.pi._build_internal_graph(conn, norm_proj)
            file_rows = conn.execute(
                "SELECT rel_path, ext, is_test, line_count FROM indexed_files WHERE project_path = ? ORDER BY rel_path",
                (norm_proj,),
            ).fetchall()
            sym_rows = conn.execute(
                "SELECT rel_path, name, kind, start_line, end_line, signature, docstring, calls_json FROM symbols WHERE project_path = ?",
                (norm_proj,),
            ).fetchall()

        modules: dict[str, list[str]] = defaultdict(list)
        file_nodes: list[dict] = []
        public_interfaces: list[dict] = []
        services: list[dict] = []
        inputs_outputs: list[dict] = []
        interface_contracts: list[dict] = []
        call_graph: list[dict] = []
        business_logic_files: list[str] = []
        reusable_components: list[dict] = []

        in_degree: dict[str, int] = defaultdict(int)
        for src, tgts in adj.items():
            for t in tgts:
                in_degree[t] += 1

        for r in file_rows:
            rp = r["rel_path"]
            mod = str(Path(rp).parent) if "/" in rp else "root"
            modules[mod].append(rp)
            fpath = root / rp
            text = ""
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

            layer_info = self.classify_file_layer(rp, text, bool(r["is_test"]))
            if layer_info["has_business_logic"] and not r["is_test"]:
                business_logic_files.append(rp)

            # Extraer rutas/contratos API
            for rm in _ROUTE_RE.finditer(text):
                method = (rm.group(1) or rm.group(3) or "HTTP").upper()
                route_path = rm.group(2) or rm.group(4) or rm.group(5) or ""
                if route_path:
                    interface_contracts.append({"type": "http_endpoint", "method": method, "path": route_path, "file": rp})

            if r["ext"] == ".py" and text:
                py_info = _extract_python_io_and_contracts(text, rp)
                public_interfaces.extend(py_info["public_interfaces"])
                services.extend(py_info["services"])
                inputs_outputs.extend(py_info["inputs_outputs"])
                call_graph.extend(py_info["call_edges"])

                # Componentes reutilizables: funciones/clases públicas en archivos sin acoplamiento UI/CLI
                if not r["is_test"] and not layer_info["has_ui"]:
                    for iface in py_info["public_interfaces"]:
                        if iface["kind"] in {"function", "async_function", "class"} and iface["symbol"] != "main":
                            reusable_components.append(
                                {
                                    "symbol": iface["symbol"],
                                    "kind": iface["kind"],
                                    "file": rp,
                                    "line": iface["line"],
                                    "layer": layer_info["layer"],
                                    "in_degree": in_degree.get(rp, 0),
                                    "decoupled_from_ui": not layer_info["has_ui"] and not layer_info["has_cli"],
                                }
                            )

            file_nodes.append(
                {
                    "rel_path": rp,
                    "module": mod,
                    "language": _LANG_BY_EXT.get(r["ext"].lower(), "Other"),
                    "lines": int(r["line_count"] or 0),
                    "is_test": bool(r["is_test"]),
                    "layer": layer_info["layer"],
                    "depends_on": sorted(adj.get(rp, set())),
                    "depended_by_count": in_degree.get(rp, 0),
                }
            )

        # Relaciones entre módulos (directorio -> directorio)
        mod_edges: set[tuple[str, str]] = set()
        for src, tgts in adj.items():
            m_src = str(Path(src).parent) if "/" in src else "root"
            for tgt in tgts:
                m_tgt = str(Path(tgt).parent) if "/" in tgt else "root"
                if m_src != m_tgt:
                    mod_edges.add((m_src, m_tgt))

        # Flujos de ejecución a partir de los entry points detectados
        execution_flows: list[dict] = []
        for ep in repo_map.get("entry_points", [])[:8]:
            trace = self.pi.trace_execution_paths(ep["rel_path"], root, max_depth=3)
            execution_flows.append(
                {
                    "entry_point": ep["rel_path"],
                    "reasons": ep["reasons"],
                    "downstream_modules": trace.get("downstream_dependencies", [])[:12],
                }
            )

        functions_list = [
            {"file": s["rel_path"], "name": s["name"], "line": s["start_line"], "signature": s["signature"], "calls": json.loads(s["calls_json"] or "[]")}
            for s in sym_rows
            if s["kind"] in {"function", "method", "shell_fn", "rust_symbol", "go_symbol"}
        ]
        classes_list = [
            {"file": s["rel_path"], "name": s["name"], "line": s["start_line"], "signature": s["signature"]}
            for s in sym_rows
            if s["kind"] in {"class", "interface", "type"}
        ]

        reusable_components.sort(key=lambda c: (1 if c["decoupled_from_ui"] else 0, c["in_degree"]), reverse=True)

        return {
            "ok": True,
            "project_path": norm_proj,
            "parser_backend": self.ts_info,
            "index_stats": idx_stats,
            "codebase_intelligence": {
                "languages": lang_fw["languages"],
                "primary_language": lang_fw["primary_language"],
                "frameworks": lang_fw["frameworks"],
                "external_dependencies": lang_fw["external_dependencies"],
                "modules": {k: sorted(v) for k, v in sorted(modules.items())},
                "business_logic_files": sorted(business_logic_files),
                "reusable_components": reusable_components[:40],
                "duplicate_blocks": repo_map.get("duplicate_blocks", []),
                "circular_dependencies": repo_map.get("circular_dependencies", []),
                "critical_modules": repo_map.get("critical_modules", []),
            },
            "repository_graph": {
                "files": file_nodes,
                "functions_count": len(functions_list),
                "functions": functions_list[:200],
                "classes_count": len(classes_list),
                "classes": classes_list[:100],
                "services": services[:50],
                "dependencies": {k: sorted(v) for k, v in adj.items() if v},
                "module_relations": [{"from": a, "to": b} for a, b in sorted(mod_edges)],
                "call_graph": call_graph[:250],
                "execution_flows": execution_flows,
                "inputs_outputs": inputs_outputs[:120],
                "public_interfaces": public_interfaces[:100],
                "interface_contracts": interface_contracts[:80],
            },
            "repo_map_text": repo_map.get("repo_map_text", ""),
        }

    def gather_pre_modification_context(
        self,
        target_or_objective: str,
        project_path: Path | str,
        max_chars: int = 4000,
    ) -> dict:
        """
        C. Context Intelligence: antes de modificar código recupera:
        1. Archivos relacionados con la tarea.
        2. Dependencias afectadas (downstream y upstream).
        3. Funciones exactas que consumen los módulos/símbolos modificados.
        4. Pruebas existentes.
        5. Decisiones arquitectónicas previas.
        """
        root = Path(project_path).resolve()
        norm_proj = str(root)
        self.pi.index_project(root)

        target = target_or_objective.strip()
        is_direct_file = (root / target).is_file()
        related_hits = self.pi.search_hybrid(target, root, limit=10)
        primary_file = target if is_direct_file else (related_hits[0]["rel_path"] if related_hits else "")

        impact = self.pi.get_impact_and_tests(primary_file or target, root) if (primary_file or target) else {}
        trace = self.pi.trace_execution_paths(primary_file or target, root, max_depth=3) if (primary_file or target) else {}

        # Encontrar funciones exactas que consumen símbolos definidos en el archivo objetivo
        consuming_functions: list[dict] = []
        defined_syms: list[str] = []
        if primary_file:
            with self.pi._connect() as conn:
                defined_syms = [
                    r["name"].split(".")[-1]
                    for r in conn.execute(
                        "SELECT name FROM symbols WHERE project_path = ? AND rel_path = ?",
                        (norm_proj, primary_file),
                    ).fetchall()
                ]
                stem = Path(primary_file).stem
                other_syms = conn.execute(
                    "SELECT rel_path, name, start_line, calls_json FROM symbols WHERE project_path = ? AND rel_path != ?",
                    (norm_proj, primary_file),
                ).fetchall()
            target_names = set(defined_syms) | {stem}
            for row in other_syms:
                calls = set(json.loads(row["calls_json"] or "[]"))
                matched_calls = sorted(calls & target_names)
                if matched_calls:
                    consuming_functions.append(
                        {
                            "consumer_file": row["rel_path"],
                            "consumer_function": row["name"],
                            "line": row["start_line"],
                            "calls_target_symbols": matched_calls[:6],
                        }
                    )

        prior_decisions: list[dict] = []
        if self.memory is not None:
            stem_hint = Path(primary_file).stem if primary_file else ""
            mem_query = " ".join([target, primary_file, stem_hint, *defined_syms[:8]]).strip()
            mems = self.memory.retrieve_relevant_memories(
                query=mem_query,
                project_path=norm_proj,
                tiers=["project"],
                include_provisional=False,
                limit=6,
            )
            prior_decisions = [
                {
                    "id": m["id"],
                    "title": m["title"],
                    "category": m["category"],
                    "content": m["content"][:260],
                    "created_at": m["created_at"],
                }
                for m in mems
            ]

        summary_lines = [
            f"[CONTEXT_INTELLIGENCE] target={primary_file or target}",
            "Related files: " + ", ".join(h["rel_path"] for h in related_hits[:6]),
            "Affected dependents: " + ", ".join(impact.get("dependent_files", [])[:8]),
            "Consuming functions: "
            + ", ".join(f"{c['consumer_file']}::{c['consumer_function']}" for c in consuming_functions[:8]),
            "Existing tests: " + ", ".join(impact.get("related_tests", [])[:6]),
        ]
        if prior_decisions:
            summary_lines.append(
                "Prior ADRs: " + " | ".join(d["title"] for d in prior_decisions[:4])
            )

        return {
            "ok": True,
            "target": target,
            "primary_file": primary_file,
            "related_files": related_hits,
            "affected_dependencies": {
                "dependent_files": impact.get("dependent_files", []),
                "downstream_dependencies": trace.get("downstream_dependencies", []),
                "upstream_callers": trace.get("upstream_callers", []),
            },
            "consuming_functions": consuming_functions[:30],
            "existing_tests": impact.get("related_tests", []),
            "prior_architectural_decisions": prior_decisions,
            "context_summary": "\n".join(summary_lines)[:max_chars],
        }
