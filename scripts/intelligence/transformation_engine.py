#!/usr/bin/env python3
"""
Semantic Project Transformation Engine — OpenCode-Saghet (Fase 4 / v0.5.0).

Motor capaz de transformar aplicaciones entre interfaces y plataformas conservando
su lógica funcional real (CLI -> Web, CLI -> Desktop, CLI -> Mobile, Web <-> Desktop,
monolito -> modular, local -> cliente-servidor, automatización -> SaaS).

REGLA FUNDAMENTAL:
Jamás confundir la interfaz original (CLI) con la lógica funcional de la aplicación.
NUNCA genera páginas que impriman comandos de terminal ni wrappers de subprocesos CLI.
Extrae las funciones/reglas de dominio reales, las separa en capas proporcionales al
tamaño del proyecto, construye API + interfaz gráfica real y valida la equivalencia
funcional mediante una Matriz de Equivalencia ejecutable.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import shutil
from pathlib import Path
from typing import Callable

from scripts.intelligence.semantic_engine import SemanticProjectEngine
from scripts.intelligence.visual_product import design_ui_product_blueprint, validate_ui_product_integrity

SUPPORTED_TRANSFORMATIONS = (
    "cli_to_web",
    "cli_to_desktop",
    "cli_to_mobile",
    "web_to_desktop",
    "desktop_to_web",
    "monolith_to_modular",
    "local_to_client_server",
    "automation_to_saas",
)


def _literal_value(node: ast.AST | None):
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_literal_value(e) for e in node.elts]
    if isinstance(node, ast.Name):
        return node.id
    return None


def analyze_cli_application(source_path: Path | str) -> dict:
    """
    Analiza una herramienta CLI Python mediante AST para extraer:
    1. Comandos/subcomandos (`argparse` subparsers, `click`, `typer` o funciones públicas).
    2. Parámetros, tipos, valores por defecto, choices y obligatoriedad.
    3. Funciones de lógica de negocio puras (separadas de argparse/print/sys.exit).
    4. Mapeo comando -> función de dominio real.
    """
    src = Path(source_path).resolve()
    py_files = [src] if src.is_file() else sorted(
        p for p in src.rglob("*.py")
        if not any(part in {".git", "__pycache__", ".venv", "tests", "build", "dist"} for part in p.parts)
    )
    if not py_files:
        return {"ok": False, "error": f"No se encontraron archivos Python en {src}"}

    commands: list[dict] = []
    domain_functions: list[dict] = []
    cli_entry_file: str | None = None

    for fpath in py_files:
        rel = fpath.name if src.is_file() else str(fpath.relative_to(src))
        text = fpath.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        is_cli_file = "argparse" in text or "click" in text or "typer" in text or "sys.argv" in text
        if is_cli_file and cli_entry_file is None:
            cli_entry_file = rel

        # Identificar funciones de negocio puras (sin argparse ni sys.exit)
        fn_map: dict[str, dict] = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                fn_src = ast.get_source_segment(text, node) or ""
                is_cli_glue = node.name in {"main", "cli", "build_parser", "parse_args"} or "ArgumentParser" in fn_src
                params = []
                defaults_pad = [None] * (len(node.args.args) - len(node.args.defaults)) + list(node.args.defaults)
                for arg, dflt in zip(node.args.args, defaults_pad):
                    ann = ast.unparse(arg.annotation) if arg.annotation else "str"
                    params.append(
                        {
                            "name": arg.arg,
                            "type": ann,
                            "required": dflt is None,
                            "default": _literal_value(dflt),
                        }
                    )
                ret = ast.unparse(node.returns) if node.returns else "Any"
                info = {
                    "name": node.name,
                    "file": rel,
                    "line": node.lineno,
                    "parameters": params,
                    "returns": ret,
                    "docstring": (ast.get_docstring(node) or "").strip(),
                    "is_cli_glue": is_cli_glue,
                }
                fn_map[node.name] = info
                if not is_cli_glue and not node.name.startswith("_"):
                    domain_functions.append(info)

        # Extraer subcomandos de argparse (subparsers.add_parser("cmd", help=...))
        subparser_vars: dict[str, dict] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call = node.value
                if isinstance(call.func, ast.Attribute) and call.func.attr == "add_parser" and call.args:
                    cmd_name = str(_literal_value(call.args[0]) or "")
                    help_txt = ""
                    for kw in call.keywords:
                        if kw.arg == "help":
                            help_txt = str(_literal_value(kw.value) or "")
                    if cmd_name and node.targets and isinstance(node.targets[0], ast.Name):
                        var_name = node.targets[0].id
                        subparser_vars[var_name] = {
                            "name": cmd_name,
                            "label": cmd_name.replace("_", " ").replace("-", " ").title(),
                            "description": help_txt or f"Operación {cmd_name}",
                            "parameters": [],
                            "handler": None,
                            "source_file": rel,
                        }

        # Extraer add_argument y set_defaults en cada subparser
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value.id if isinstance(node.func.value, ast.Name) else ""
                if owner not in subparser_vars:
                    continue
                if node.func.attr == "add_argument" and node.args:
                    raw_arg = str(_literal_value(node.args[0]) or "")
                    param_name = raw_arg.lstrip("-").replace("-", "_")
                    is_opt = raw_arg.startswith("-")
                    p_type = "str"
                    p_default = None
                    p_choices = None
                    p_help = ""
                    p_req = not is_opt
                    for kw in node.keywords:
                        if kw.arg == "type":
                            p_type = str(_literal_value(kw.value) or "str")
                        elif kw.arg == "default":
                            p_default = _literal_value(kw.value)
                        elif kw.arg == "choices":
                            p_choices = _literal_value(kw.value)
                        elif kw.arg == "help":
                            p_help = str(_literal_value(kw.value) or "")
                        elif kw.arg == "required":
                            p_req = bool(_literal_value(kw.value))
                        elif kw.arg == "action" and str(_literal_value(kw.value)) in {"store_true", "store_false"}:
                            p_type = "bool"
                            p_req = False
                            p_default = False
                    subparser_vars[owner]["parameters"].append(
                        {
                            "name": param_name,
                            "type": p_type,
                            "required": p_req,
                            "default": p_default,
                            "choices": p_choices,
                            "help": p_help,
                        }
                    )
                elif node.func.attr == "set_defaults":
                    for kw in node.keywords:
                        if kw.arg in {"func", "handler"} and isinstance(kw.value, ast.Name):
                            subparser_vars[owner]["handler"] = kw.value.id

        # Asociar comandos con funciones de dominio por set_defaults o coincidencia de nombre
        for cmd in subparser_vars.values():
            if not cmd["handler"]:
                cand = cmd["name"].replace("-", "_")
                if cand in fn_map and not fn_map[cand]["is_cli_glue"]:
                    cmd["handler"] = cand
                else:
                    for fn_name in fn_map:
                        if not fn_map[fn_name]["is_cli_glue"] and (cand in fn_name or fn_name in cand):
                            cmd["handler"] = fn_name
                            break
            commands.append(cmd)

    # Si el CLI no usa subparsers explícitos, mapear funciones de dominio públicas como capacidades
    if not commands and domain_functions:
        for fn in domain_functions:
            commands.append(
                {
                    "name": fn["name"],
                    "label": fn["name"].replace("_", " ").title(),
                    "description": fn["docstring"] or f"Ejecuta {fn['name']}",
                    "parameters": fn["parameters"],
                    "handler": fn["name"],
                    "source_file": fn["file"],
                }
            )

    return {
        "ok": True,
        "source_path": str(src),
        "cli_entry_file": cli_entry_file or (py_files[0].name if src.is_file() else str(py_files[0].relative_to(src))),
        "commands_count": len(commands),
        "commands": commands,
        "domain_functions": domain_functions,
    }


def propose_layered_architecture(cli_analysis: dict, target_mode: str = "cli_to_web") -> dict:
    """
    Diseña la arquitectura por capas adaptada al tamaño del proyecto (sin sobreingeniería).
    """
    mode = target_mode if target_mode in SUPPORTED_TRANSFORMATIONS else "cli_to_web"
    n_cmds = int(cli_analysis.get("commands_count", 0))
    n_fns = len(cli_analysis.get("domain_functions", []))
    size = "small" if (n_cmds <= 4 and n_fns <= 8) else ("medium" if n_cmds <= 12 else "large")

    layers = {
        "DOMAIN_LAYER": {
            "purpose": "Reglas de negocio puras, algoritmos y modelos extraídos del origen sin dependencias de CLI/UI.",
            "path": "domain/",
            "required": True,
        },
        "APPLICATION_LAYER": {
            "purpose": "Casos de uso tipados, validación de entradas y orquestación desacoplada.",
            "path": "application/",
            "required": True,
        },
        "INFRASTRUCTURE_LAYER": {
            "purpose": "Persistencia local, archivos, bases de datos y servicios externos.",
            "path": "infrastructure/",
            "required": size != "small",
        },
        "API_LAYER": {
            "purpose": "Endpoints REST/WebSocket reales consumidos por la interfaz gráfica.",
            "path": "api/",
            "required": mode in {"cli_to_web", "desktop_to_web", "local_to_client_server", "automation_to_saas", "cli_to_mobile"},
        },
        "PRESENTATION_LAYER": {
            "purpose": "Interfaz gráfica propia (Web SPA, Desktop nativo PyQt6/Tauri/Electron o Mobile) conectada a casos de uso reales.",
            "path": "presentation/" if "web" in mode else ("desktop/" if "desktop" in mode else "mobile/"),
            "required": mode != "monolith_to_modular",
        },
        "ADAPTERS": {
            "purpose": "Preserva la CLI original delegando a la misma capa Application/Domain.",
            "path": "adapters/cli.py",
            "required": True,
        },
    }
    return {
        "transformation_mode": mode,
        "project_size": size,
        "preserves_original_cli": True,
        "layers": {k: v for k, v in layers.items() if v["required"]},
    }


def _extract_clean_domain_source(source_file: Path, domain_fn_names: set[str]) -> str:
    """
    Extrae limpiamente las funciones/clases/imports de dominio de un archivo Python origen
    omitiendo el boilerplate CLI (`argparse`, `main`, `if __name__ == '__main__'`).
    """
    raw = source_file.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(raw)
    kept_blocks: list[str] = ['"""Dominio extraído automáticamente (reglas de negocio puras, sin CLI)."""', "from __future__ import annotations"]

    for node in tree.body:
        seg = ast.get_source_segment(raw, node)
        if not seg:
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod_str = seg.lower()
            if "argparse" in mod_str or "click" in mod_str or "typer" in mod_str:
                continue
            if "from __future__" in mod_str:
                continue
            kept_blocks.append(seg)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            kept_blocks.append(seg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in domain_fn_names or (not node.name.startswith("_") and node.name not in {"main", "cli", "build_parser", "parse_args"}):
                kept_blocks.append(seg)
        elif isinstance(node, ast.ClassDef):
            kept_blocks.append(seg)

    return "\n\n".join(kept_blocks) + "\n"


def _build_use_cases_module(commands: list[dict]) -> str:
    cmd_meta_json = json.dumps(commands, ensure_ascii=False)
    return f'''"""Application Layer — Casos de uso tipados y validación de entradas."""
from __future__ import annotations

import json
from typing import Any
from domain import core as domain_core

CAPABILITIES = json.loads({cmd_meta_json!r})


def _coerce_value(val: Any, ptype: str) -> Any:
    t = (ptype or "str").lower()
    if val is None or val == "":
        return None
    if t == "int":
        return int(val)
    if t == "float":
        return float(val)
    if t == "bool":
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in {{"1", "true", "yes", "si", "on"}}
    return str(val)


def list_capabilities() -> list[dict]:
    return CAPABILITIES


def execute_capability(command_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    spec = next((c for c in CAPABILITIES if c["name"] == command_name), None)
    if spec is None:
        return {{"ok": False, "error": f"Capacidad desconocida: {{command_name}}"}}
    handler_name = spec.get("handler") or command_name
    fn = getattr(domain_core, handler_name, None)
    if not callable(fn):
        return {{"ok": False, "error": f"Handler de dominio no encontrado: {{handler_name}}"}}

    kwargs: dict[str, Any] = {{}}
    for p in spec.get("parameters") or []:
        pname = p["name"]
        raw_v = payload.get(pname, p.get("default"))
        if raw_v in (None, "") and p.get("required", True):
            return {{"ok": False, "error": f"Parámetro obligatorio faltante: {{pname}}"}}
        try:
            coerced = _coerce_value(raw_v, str(p.get("type") or "str"))
        except (ValueError, TypeError) as exc:
            return {{"ok": False, "error": f"Valor inválido para '{{pname}}': {{exc}}"}}
        if coerced is not None:
            choices = p.get("choices")
            if choices and coerced not in choices:
                return {{"ok": False, "error": f"Valor '{{coerced}}' fuera de opciones permitidas {{choices}}"}}
            kwargs[pname] = coerced
        elif p.get("default") is not None:
            kwargs[pname] = p.get("default")

    try:
        result = fn(**kwargs)
        return {{"ok": True, "command": command_name, "input": kwargs, "result": result}}
    except Exception as exc:
        return {{"ok": False, "command": command_name, "error": str(exc)}}
'''


def _build_cli_adapter_module(app_title: str, commands: list[dict]) -> str:
    return f'''#!/usr/bin/env python3
"""Adapter Layer — CLI original preservada delegando a Application/Domain."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from application.use_cases import CAPABILITIES, execute_capability


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="{app_title} (CLI preservada)")
    sub = parser.add_subparsers(dest="command", required=True)
    type_map = {{"int": int, "float": float, "str": str}}
    for cap in CAPABILITIES:
        sp = sub.add_parser(cap["name"], help=cap.get("description") or "")
        for p in cap.get("parameters") or []:
            pname = p["name"]
            ptype = type_map.get(str(p.get("type") or "str").lower(), str)
            if p.get("required", True):
                sp.add_argument(pname, type=ptype, choices=p.get("choices") or None)
            else:
                flag = f"--{{pname.replace('_', '-')}}"
                if str(p.get("type") or "").lower() == "bool":
                    sp.add_argument(flag, action="store_true", default=bool(p.get("default", False)))
                else:
                    sp.add_argument(flag, type=ptype, default=p.get("default"), choices=p.get("choices") or None)
    args = parser.parse_args(argv)
    payload = {{k: v for k, v in vars(args).items() if k != "command"}}
    res = execute_capability(args.command, payload)
    if not res.get("ok"):
        print(f"ERROR: {{res.get('error')}}", file=sys.stderr)
        return 1
    out = res["result"]
    print(json.dumps(out, ensure_ascii=False) if isinstance(out, (dict, list)) else str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _build_web_server_module(app_title: str) -> str:
    return f'''#!/usr/bin/env python3
"""API Layer — Servidor REST real conectado a Application/Domain y Presentation."""
from __future__ import annotations

import argparse
import http.server
import json
import socketserver
import sys
import urllib.parse
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PRESENTATION_DIR = ROOT_DIR / "presentation"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from application.use_cases import execute_capability, list_capabilities


class AppHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_file(self, path: Path, content_type: str) -> None:
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json(200, {{"ok": True, "app": "{app_title}", "layer": "api"}})
            return
        if parsed.path == "/api/capabilities":
            self._send_json(200, {{"ok": True, "app": "{app_title}", "capabilities": list_capabilities()}})
            return
        if parsed.path in {{"/", "/index.html"}}:
            self._send_file(PRESENTATION_DIR / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._send_file(PRESENTATION_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self._send_file(PRESENTATION_DIR / "styles.css", "text/css; charset=utf-8")
            return
        self._send_json(404, {{"ok": False, "error": "Ruta no encontrada"}})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/actions/"):
            cmd = parsed.path[len("/api/actions/"):].strip("/")
            length = int(self.headers.get("Content-Length") or 0)
            raw_body = self.rfile.read(min(length, 262144)) if length > 0 else b"{{}}"
            try:
                body = json.loads(raw_body.decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("JSON debe ser un objeto")
            except Exception as exc:
                self._send_json(400, {{"ok": False, "error": f"JSON inválido: {{exc}}"}})
                return
            res = execute_capability(cmd, body)
            self._send_json(200 if res.get("ok") else 400, res)
            return
        self._send_json(404, {{"ok": False, "error": "Endpoint POST no encontrado"}})


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser(description="{app_title} Web Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with ReusableTCPServer((args.host, args.port), AppHandler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
'''


def _build_web_presentation_files(app_title: str) -> tuple[str, str, str]:
    html = f'''<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{app_title}</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <div class="layout">
      <header class="topbar">
        <h1>{app_title}</h1>
        <span id="health-badge" class="badge" aria-live="polite">Conectando...</span>
      </header>
      <div class="workspace">
        <nav id="nav-sidebar" class="sidebar" aria-label="Navegación de capacidades"></nav>
        <main id="main-content" class="main">
          <section id="workspace-panel" class="card">
            <h2 id="panel-title">Cargando capacidades...</h2>
            <p id="panel-desc" class="muted"></p>
            <div id="error-banner" class="alert hidden" role="alert"></div>
            <form id="action-form" class="form-grid"></form>
            <section class="result-section">
              <h3>Resultado</h3>
              <div id="result-view" class="result-box" aria-live="polite">Ejecuta una acción para ver resultados reales.</div>
            </section>
          </section>
          <section class="card">
            <h3>Historial de Ejecuciones</h3>
            <table class="history-table">
              <thead>
                <tr><th>Acción</th><th>Entrada</th><th>Resultado</th><th>Estado</th></tr>
              </thead>
              <tbody id="history-body"></tbody>
            </table>
          </section>
        </main>
      </div>
    </div>
    <script src="/app.js"></script>
  </body>
</html>
'''
    js = '''const state = { capabilities: [], active: null, history: [] };

async function boot() {
  const badge = document.getElementById("health-badge");
  try {
    const hRes = await fetch("/api/health");
    const health = await hRes.json();
    badge.textContent = health.ok ? "API Activa" : "API Degradada";
    const cRes = await fetch("/api/capabilities");
    const cData = await cRes.json();
    state.capabilities = cData.capabilities || [];
    renderNav();
    if (state.capabilities.length > 0) selectCapability(state.capabilities[0].name);
  } catch (err) {
    showError("No se pudo conectar con la API: " + err.message);
  }
}

function showError(msg) {
  const el = document.getElementById("error-banner");
  if (!msg) { el.classList.add("hidden"); el.textContent = ""; return; }
  el.textContent = msg;
  el.classList.remove("hidden");
}

function renderNav() {
  const nav = document.getElementById("nav-sidebar");
  nav.innerHTML = "";
  for (const cap of state.capabilities) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "nav-btn" + (state.active === cap.name ? " active" : "");
    btn.setAttribute("data-nav", cap.name);
    btn.textContent = cap.label || cap.name;
    btn.addEventListener("click", () => selectCapability(cap.name));
    nav.appendChild(btn);
  }
}

function selectCapability(name) {
  state.active = name;
  renderNav();
  showError("");
  const cap = state.capabilities.find((c) => c.name === name);
  if (!cap) return;
  document.getElementById("panel-title").textContent = cap.label || cap.name;
  document.getElementById("panel-desc").textContent = cap.description || "";
  const form = document.getElementById("action-form");
  form.innerHTML = "";

  for (const p of cap.parameters || []) {
    const wrap = document.createElement("div");
    wrap.className = "field";
    const label = document.createElement("label");
    label.setAttribute("for", "field_" + p.name);
    label.textContent = p.name + (p.required ? " *" : "");
    wrap.appendChild(label);

    let input;
    if (Array.isArray(p.choices) && p.choices.length > 0) {
      input = document.createElement("select");
      for (const ch of p.choices) {
        const opt = document.createElement("option");
        opt.value = ch;
        opt.textContent = ch;
        input.appendChild(opt);
      }
    } else {
      input = document.createElement("input");
      const t = String(p.type || "str").toLowerCase();
      input.type = (t === "int" || t === "float") ? "number" : (t === "bool" ? "checkbox" : "text");
      if (t === "float") input.step = "any";
    }
    input.id = "field_" + p.name;
    input.name = p.name;
    if (p.required && input.type !== "checkbox") input.required = true;
    if (p.default !== null && p.default !== undefined && input.type !== "checkbox") input.value = String(p.default);
    wrap.appendChild(input);
    form.appendChild(wrap);
  }

  const submitBtn = document.createElement("button");
  submitBtn.type = "submit";
  submitBtn.className = "btn-primary";
  submitBtn.textContent = "Ejecutar " + (cap.label || cap.name);
  form.appendChild(submitBtn);

  form.onsubmit = async (ev) => {
    ev.preventDefault();
    showError("");
    submitBtn.disabled = true;
    submitBtn.setAttribute("aria-busy", "true");
    const payload = {};
    for (const p of cap.parameters || []) {
      const el = document.getElementById("field_" + p.name);
      if (!el) continue;
      payload[p.name] = el.type === "checkbox" ? el.checked : el.value;
    }
    try {
      const resp = await fetch("/api/actions/" + encodeURIComponent(cap.name), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!data.ok) {
        showError(data.error || "Error ejecutando la operación");
      } else {
        document.getElementById("result-view").textContent =
          typeof data.result === "object" ? JSON.stringify(data.result, null, 2) : String(data.result);
      }
      state.history.unshift({ action: cap.name, input: payload, result: data.ok ? data.result : data.error, ok: Boolean(data.ok) });
      renderHistory();
    } catch (err) {
      showError("Error de red: " + err.message);
    } finally {
      submitBtn.disabled = false;
      submitBtn.removeAttribute("aria-busy");
    }
  };
}

function renderHistory() {
  const tbody = document.getElementById("history-body");
  tbody.innerHTML = "";
  for (const item of state.history.slice(0, 15)) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${item.action}</td><td>${JSON.stringify(item.input)}</td><td>${JSON.stringify(item.result)}</td><td>${item.ok ? "OK" : "ERROR"}</td>`;
    tbody.appendChild(tr);
  }
}

document.addEventListener("DOMContentLoaded", boot);
'''
    css = '''* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; }
.topbar { display: flex; justify-content: space-between; align-items: center; padding: 1rem 1.5rem; background: #1e293b; border-bottom: 1px solid #334155; }
.topbar h1 { margin: 0; font-size: 1.2rem; }
.badge { padding: 0.25rem 0.75rem; border-radius: 999px; background: #065f46; color: #ecfdf5; font-size: 0.85rem; }
.workspace { display: grid; grid-template-columns: 240px 1fr; min-height: calc(100vh - 60px); }
.sidebar { background: #111827; padding: 1rem; border-right: 1px solid #1f2937; display: flex; flex-direction: column; gap: 0.5rem; }
.nav-btn { background: transparent; color: #cbd5e1; border: 1px solid #334155; padding: 0.65rem 0.8rem; text-align: left; border-radius: 0.5rem; cursor: pointer; }
.nav-btn.active { background: #2563eb; color: #ffffff; border-color: #3b82f6; }
.main { padding: 1.5rem; display: flex; flex-direction: column; gap: 1.25rem; }
.card { background: #1e293b; border: 1px solid #334155; border-radius: 0.75rem; padding: 1.25rem; }
.muted { color: #94a3b8; }
.form-grid { display: grid; gap: 0.85rem; max-width: 560px; }
.field { display: flex; flex-direction: column; gap: 0.3rem; }
input, select { padding: 0.55rem 0.75rem; border-radius: 0.45rem; border: 1px solid #475569; background: #0f172a; color: #f8fafc; }
.btn-primary { background: #2563eb; color: #ffffff; border: none; padding: 0.7rem 1rem; border-radius: 0.5rem; cursor: pointer; font-weight: 600; }
.alert { background: #7f1d1d; color: #fee2e2; padding: 0.75rem; border-radius: 0.5rem; margin-bottom: 0.75rem; }
.hidden { display: none; }
.result-box { background: #0f172a; padding: 0.9rem; border-radius: 0.5rem; border: 1px solid #334155; white-space: pre-wrap; font-family: monospace; }
.history-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.history-table th, .history-table td { border-bottom: 1px solid #334155; padding: 0.5rem; text-align: left; }
@media (max-width: 768px) { .workspace { grid-template-columns: 1fr; } .sidebar { flex-direction: row; overflow-x: auto; } }
'''
    return html, js, css


def _build_pyqt6_desktop_module(app_title: str) -> str:
    return f'''#!/usr/bin/env python3
"""Presentation Layer (Desktop) — Aplicación nativa PyQt6 conectada a Application/Domain."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from application.use_cases import execute_capability, list_capabilities


class DesktopProductWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("{app_title}")
        self.resize(860, 560)
        self.capabilities = list_capabilities()
        self.active_cap: dict | None = None
        self.field_widgets: dict[str, QWidget] = {{}}

        root_widget = QWidget()
        layout = QHBoxLayout(root_widget)

        self.nav_list = QListWidget()
        for cap in self.capabilities:
            self.nav_list.addItem(cap.get("label") or cap["name"])
        self.nav_list.currentRowChanged.connect(self.select_index)
        layout.addWidget(self.nav_list, 1)

        right = QVBoxLayout()
        self.title_label = QLabel("{app_title}")
        self.status_label = QLabel("Listo")
        self.form_container = QWidget()
        self.form_layout = QFormLayout(self.form_container)
        self.run_button = QPushButton("Ejecutar")
        self.run_button.clicked.connect(self.run_active_action)
        self.output_view = QTextEdit()
        self.output_view.setReadOnly(True)

        right.addWidget(self.title_label)
        right.addWidget(self.form_container)
        right.addWidget(self.run_button)
        right.addWidget(self.status_label)
        right.addWidget(self.output_view, 1)
        layout.addLayout(right, 3)

        self.setCentralWidget(root_widget)
        if self.capabilities:
            self.nav_list.setCurrentRow(0)

    def select_index(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.capabilities):
            return
        self.active_cap = self.capabilities[idx]
        self.title_label.setText(self.active_cap.get("label") or self.active_cap["name"])
        while self.form_layout.rowCount() > 0:
            self.form_layout.removeRow(0)
        self.field_widgets.clear()

        for p in self.active_cap.get("parameters") or []:
            pname = p["name"]
            if p.get("choices"):
                w = QComboBox()
                for ch in p["choices"]:
                    w.addItem(str(ch))
            elif str(p.get("type") or "").lower() == "bool":
                w = QCheckBox()
                w.setChecked(bool(p.get("default", False)))
            else:
                w = QLineEdit()
                if p.get("default") is not None:
                    w.setText(str(p["default"]))
            self.field_widgets[pname] = w
            self.form_layout.addRow(pname, w)

    def collect_payload(self) -> dict:
        payload = {{}}
        for pname, w in self.field_widgets.items():
            if isinstance(w, QComboBox):
                payload[pname] = w.currentText()
            elif isinstance(w, QCheckBox):
                payload[pname] = w.isChecked()
            elif isinstance(w, QLineEdit):
                payload[pname] = w.text()
        return payload

    def run_active_action(self) -> dict:
        if not self.active_cap:
            return {{"ok": False, "error": "Sin capacidad seleccionada"}}
        res = execute_capability(self.active_cap["name"], self.collect_payload())
        if res.get("ok"):
            self.status_label.setText("OK")
            val = res["result"]
            self.output_view.setPlainText(json.dumps(val, ensure_ascii=False, indent=2) if isinstance(val, (dict, list)) else str(val))
        else:
            self.status_label.setText(f"ERROR: {{res.get('error')}}")
            self.output_view.setPlainText(str(res.get("error")))
        return res


def main() -> int:
    app = QApplication(sys.argv)
    win = DesktopProductWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
'''


class SemanticTransformationEngine:
    """
    Orquestador de transformaciones semánticas entre plataformas con separación de capas,
    validación anti-UI falsa y Matriz de Equivalencia Funcional ejecutable.
    """

    def __init__(self, semantic_engine: SemanticProjectEngine | None = None) -> None:
        self.semantic = semantic_engine or SemanticProjectEngine()

    def transform_cli_to_web(
        self,
        source_path: Path | str,
        output_dir: Path | str,
        app_title: str = "Transformed Web Application",
    ) -> dict:
        """Transforma una CLI Python real en una aplicación Web funcional + API + CLI preservada."""
        analysis = analyze_cli_application(source_path)
        if not analysis.get("ok"):
            return analysis

        src = Path(source_path).resolve()
        entry_file = src if src.is_file() else (src / analysis["cli_entry_file"])
        out = Path(output_dir).resolve()
        for sub in ("domain", "application", "api", "presentation", "adapters"):
            (out / sub).mkdir(parents=True, exist_ok=True)
            if sub != "presentation":
                (out / sub / "__init__.py").write_text("", encoding="utf-8")

        domain_fn_names = {f["name"] for f in analysis["domain_functions"]}
        domain_code = _extract_clean_domain_source(entry_file, domain_fn_names)
        (out / "domain" / "core.py").write_text(domain_code, encoding="utf-8")
        (out / "application" / "use_cases.py").write_text(_build_use_cases_module(analysis["commands"]), encoding="utf-8")
        (out / "api" / "server.py").write_text(_build_web_server_module(app_title), encoding="utf-8")
        (out / "adapters" / "cli.py").write_text(_build_cli_adapter_module(app_title, analysis["commands"]), encoding="utf-8")

        html, js, css = _build_web_presentation_files(app_title)
        (out / "presentation" / "index.html").write_text(html, encoding="utf-8")
        (out / "presentation" / "app.js").write_text(js, encoding="utf-8")
        (out / "presentation" / "styles.css").write_text(css, encoding="utf-8")

        arch = propose_layered_architecture(analysis, "cli_to_web")
        blueprint = design_ui_product_blueprint(app_title, analysis["commands"], target_platform="web", prefer_zero_build=True)
        ui_check = validate_ui_product_integrity(out)

        return {
            "ok": ui_check["ok"],
            "transformation_mode": "cli_to_web",
            "output_dir": str(out),
            "cli_analysis": analysis,
            "architecture": arch,
            "ui_blueprint": blueprint,
            "ui_integrity_validation": ui_check,
            "generated_files": [
                "domain/core.py",
                "application/use_cases.py",
                "api/server.py",
                "presentation/index.html",
                "presentation/app.js",
                "presentation/styles.css",
                "adapters/cli.py",
            ],
        }

    def transform_cli_to_desktop(
        self,
        source_path: Path | str,
        output_dir: Path | str,
        app_title: str = "Transformed Desktop Application",
    ) -> dict:
        """Transforma una CLI Python real en una aplicación de Escritorio nativa PyQt6 + CLI preservada."""
        analysis = analyze_cli_application(source_path)
        if not analysis.get("ok"):
            return analysis

        src = Path(source_path).resolve()
        entry_file = src if src.is_file() else (src / analysis["cli_entry_file"])
        out = Path(output_dir).resolve()
        for sub in ("domain", "application", "desktop", "adapters"):
            (out / sub).mkdir(parents=True, exist_ok=True)
            (out / sub / "__init__.py").write_text("", encoding="utf-8")

        domain_fn_names = {f["name"] for f in analysis["domain_functions"]}
        domain_code = _extract_clean_domain_source(entry_file, domain_fn_names)
        (out / "domain" / "core.py").write_text(domain_code, encoding="utf-8")
        (out / "application" / "use_cases.py").write_text(_build_use_cases_module(analysis["commands"]), encoding="utf-8")
        (out / "desktop" / "app.py").write_text(_build_pyqt6_desktop_module(app_title), encoding="utf-8")
        (out / "adapters" / "cli.py").write_text(_build_cli_adapter_module(app_title, analysis["commands"]), encoding="utf-8")

        arch = propose_layered_architecture(analysis, "cli_to_desktop")
        blueprint = design_ui_product_blueprint(app_title, analysis["commands"], target_platform="desktop")
        ui_check = validate_ui_product_integrity(out)

        return {
            "ok": ui_check["ok"],
            "transformation_mode": "cli_to_desktop",
            "pyqt6_available": importlib.util.find_spec("PyQt6") is not None,
            "output_dir": str(out),
            "cli_analysis": analysis,
            "architecture": arch,
            "ui_blueprint": blueprint,
            "ui_integrity_validation": ui_check,
            "generated_files": [
                "domain/core.py",
                "application/use_cases.py",
                "desktop/app.py",
                "adapters/cli.py",
            ],
        }

    @staticmethod
    def verify_functional_equivalence(
        cases: list[dict],
        original_runner: Callable[[dict], str],
        transformed_runner: Callable[[dict], str],
    ) -> dict:
        """
        Ejecuta cada caso en la aplicación original y en la transformada, generando
        la Matriz de Equivalencia Funcional obligatoria (Fase 4 y Fase 8).
        """
        matrix: list[dict] = []
        passed = 0
        for case in cases:
            orig_out = str(original_runner(case)).strip()
            new_out = str(transformed_runner(case)).strip()
            eq = orig_out == new_out
            if eq:
                passed += 1
            matrix.append(
                {
                    "original_feature": case.get("feature") or case.get("command"),
                    "new_implementation": case.get("new_target") or f"action:{case.get('command')}",
                    "test": case.get("test_name") or f"equiv_{case.get('command')}",
                    "original_output": orig_out,
                    "new_output": new_out,
                    "result": "PASS" if eq else "FAIL",
                }
            )
        total = len(cases)
        return {
            "ok": total > 0 and passed == total,
            "passed": passed,
            "total": total,
            "equivalence_rate_pct": round((passed / max(1, total)) * 100.0, 1),
            "matrix": matrix,
        }
