#!/usr/bin/env python3
"""
Visual Product Engineering & Anti-Fake UI Validator — OpenCode-Saghet (Fase 5 / v0.5.0).

Garantiza que las aplicaciones construidas sean productos gráficos reales conectados a
funcionalidades reales (nunca botones decorativos, datos falsos, simulaciones ni páginas
que simplemente impriman comandos de terminal).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

# Catálogo estructurado de combinaciones coherentes (nunca mezclar múltiples frameworks del mismo nivel)
STACK_CATALOG: dict[str, dict[str, dict]] = {
    "web": {
        "python_lightweight": {
            "frontend": "Vanilla HTML5/CSS3/ES2023 (Zero-Build SPA)",
            "backend": "Python HTTP/FastAPI REST",
            "rationale": "Cero pasos de compilación para herramientas internas o entregas rápidas sobre dominio Python.",
        },
        "react_fastapi": {
            "frontend": "React + TypeScript (Vite)",
            "backend": "FastAPI (Python)",
            "rationale": "Ecosistema maduro de dashboards/formularios complejos conectado a dominio Python tipado.",
        },
        "nextjs_node": {
            "frontend": "Next.js + React + TypeScript",
            "backend": "Node.js / NestJS",
            "rationale": "Ideal para aplicaciones SaaS full-stack en TypeScript con SSR y rutas API integradas.",
        },
        "svelte_go": {
            "frontend": "Svelte + TypeScript",
            "backend": "Go (net/http / Gin)",
            "rationale": "Alto rendimiento, bundle mínimo y concurrencia nativa en backend.",
        },
        "vue_rust": {
            "frontend": "Vue 3 + TypeScript",
            "backend": "Rust (Axum)",
            "rationale": "Curva de aprendizaje suave en UI con máxima eficiencia y seguridad de memoria en servidor.",
        },
    },
    "desktop": {
        "pyqt6_native": {
            "desktop": "Qt (PyQt6 nativo)",
            "backend": "Capa de Dominio/Aplicación Python local",
            "rationale": "Integración nativa directa en Linux/Garuda con dominio Python sin overhead de navegador embebido.",
        },
        "tauri_rust": {
            "desktop": "Tauri (Rust + WebView)",
            "backend": "Rust / Sidecar de Dominio",
            "rationale": "Binario ligero, bajo consumo de RAM y seguridad estricta de capacidades.",
        },
        "electron_ts": {
            "desktop": "Electron + TypeScript",
            "backend": "Node.js IPC",
            "rationale": "Óptimo cuando el proyecto origen ya está escrito en Node.js/TypeScript.",
        },
    },
    "mobile": {
        "flutter": {
            "mobile": "Flutter (Dart)",
            "backend": "REST/WebSocket API (FastAPI / Go)",
            "rationale": "Renderizado nativo consistente en Android/iOS desde una sola base de código.",
        },
        "react_native": {
            "mobile": "React Native (TypeScript)",
            "backend": "Node.js / NestJS / FastAPI",
            "rationale": "Máxima reutilización de tipos y lógica compartida cuando el equipo ya usa React/TypeScript.",
        },
    },
}

_DECORATIVE_BUTTON_RE = re.compile(r"<button\b([^>]*)>(.*?)</button>", re.IGNORECASE | re.DOTALL)
_FAKE_DATA_RE = re.compile(
    r"\b(TODO:\s*(?:connect|wire|implement)|mockData\b|fakeResponse\b|dummyResult\b|NotImplementedError|coming\s+soon\s*\(\))\b",
    re.IGNORECASE,
)
_CLI_WRAPPER_ANTIPATTERN_RE = re.compile(
    r"(?:copiar\s+comando|copy\s+command|ejecuta\s+en\s+tu\s+terminal|run\s+this\s+command\s+in\s+terminal|xterm\.js|<pre[^>]*>\s*\$\s*[a-z0-9_-]+)",
    re.IGNORECASE,
)


def select_product_stack(
    target_platform: str = "web",
    source_language: str = "Python",
    project_size: str = "medium",
    prefer_zero_build: bool = False,
) -> dict:
    """
    Selecciona una única combinación tecnológica adecuada según plataforma, lenguaje origen y tamaño.
    Jamás mezcla múltiples frameworks de la misma categoría.
    """
    plat = (target_platform or "web").strip().lower()
    lang = (source_language or "Python").strip().lower()
    size = (project_size or "medium").strip().lower()

    if plat == "desktop":
        has_pyqt6 = importlib.util.find_spec("PyQt6") is not None
        if lang == "python" and (has_pyqt6 or prefer_zero_build):
            chosen_key = "pyqt6_native"
            alts = ["tauri_rust", "electron_ts"]
        elif lang in {"javascript", "typescript"}:
            chosen_key = "electron_ts"
            alts = ["tauri_rust", "pyqt6_native"]
        else:
            chosen_key = "tauri_rust"
            alts = ["pyqt6_native", "electron_ts"]
        chosen = STACK_CATALOG["desktop"][chosen_key]
    elif plat == "mobile":
        chosen_key = "react_native" if lang in {"javascript", "typescript"} else "flutter"
        alts = [k for k in STACK_CATALOG["mobile"] if k != chosen_key]
        chosen = STACK_CATALOG["mobile"][chosen_key]
    else:
        plat = "web"
        if prefer_zero_build or (lang == "python" and size == "small"):
            chosen_key = "python_lightweight"
            alts = ["react_fastapi", "svelte_go"]
        elif lang == "python":
            chosen_key = "react_fastapi"
            alts = ["python_lightweight", "nextjs_node"]
        elif lang in {"javascript", "typescript"}:
            chosen_key = "nextjs_node"
            alts = ["react_fastapi", "svelte_go"]
        elif lang == "go":
            chosen_key = "svelte_go"
            alts = ["react_fastapi", "vue_rust"]
        elif lang == "rust":
            chosen_key = "vue_rust"
            alts = ["svelte_go", "react_fastapi"]
        else:
            chosen_key = "react_fastapi"
            alts = ["python_lightweight", "nextjs_node"]
        chosen = STACK_CATALOG["web"][chosen_key]

    return {
        "target_platform": plat,
        "stack_id": chosen_key,
        "selected": chosen,
        "alternatives_evaluated": [
            {"stack_id": k, **STACK_CATALOG[plat][k]} for k in alts if k in STACK_CATALOG[plat]
        ],
        "single_coherent_stack": True,
    }


def design_ui_product_blueprint(
    app_name: str,
    capabilities: list[dict],
    target_platform: str = "web",
    source_language: str = "Python",
    project_size: str = "medium",
    prefer_zero_build: bool = False,
) -> dict:
    """
    Diseña la arquitectura visual de producto: navegación, formularios reales, dashboard,
    gestión de estado, validación de entradas, manejo de errores, accesibilidad y diseño responsive.
    """
    stack = select_product_stack(target_platform, source_language, project_size, prefer_zero_build=prefer_zero_build)
    views: list[dict] = [
        {
            "id": "overview",
            "title": "Panel Principal",
            "kind": "dashboard",
            "widgets": ["kpi_summary", "recent_executions_table", "quick_actions"],
            "api_binding": "GET /api/capabilities",
        }
    ]
    forms: list[dict] = []
    for cap in capabilities:
        cname = str(cap.get("name") or "action")
        params = list(cap.get("parameters") or [])
        views.append(
            {
                "id": f"view_{cname}",
                "title": cap.get("label") or cname.replace("_", " ").replace("-", " ").title(),
                "kind": "interactive_workspace",
                "description": cap.get("description") or f"Ejecución funcional de {cname}",
                "api_binding": f"POST /api/actions/{cname}",
                "domain_handler": cap.get("handler") or cname,
            }
        )
        forms.append(
            {
                "action": cname,
                "endpoint": f"/api/actions/{cname}",
                "fields": [
                    {
                        "name": p.get("name"),
                        "input_type": _map_param_to_input_type(str(p.get("type") or "str"), p.get("choices")),
                        "required": bool(p.get("required", True)),
                        "default": p.get("default"),
                        "choices": p.get("choices") or [],
                        "validation": _validation_rule(p),
                    }
                    for p in params
                ],
                "error_state": "inline_validation_and_alert_banner",
                "loading_state": "disable_submit_with_aria_busy",
            }
        )

    return {
        "app_name": app_name,
        "stack": stack,
        "navigation": {
            "pattern": "responsive_sidebar_plus_topbar",
            "items": [{"id": v["id"], "label": v["title"]} for v in views],
        },
        "views": views,
        "forms": forms,
        "state_management": "centralized_unidirectional_store_with_history",
        "accessibility": {
            "landmarks": ["header", "nav", "main"],
            "keyboard_navigation": True,
            "aria_live_regions": True,
            "explicit_form_labels": True,
        },
        "responsive_breakpoints": {"mobile": "<= 768px", "tablet": "769px..1024px", "desktop": ">= 1025px"},
        "product_integrity_rules": [
            "prohibit_decorative_unwired_buttons",
            "prohibit_fake_or_mock_data_as_real",
            "prohibit_terminal_command_printing_pages",
            "every_control_bound_to_real_domain_or_api",
        ],
    }


def _map_param_to_input_type(py_type: str, choices: list | None = None) -> str:
    if choices:
        return "select"
    low = py_type.lower()
    if low in {"int", "float", "number", "decimal"}:
        return "number"
    if low in {"bool", "boolean"}:
        return "checkbox"
    return "text"


def _validation_rule(param: dict) -> str:
    rules = []
    if param.get("required", True):
        rules.append("required")
    ptype = str(param.get("type") or "str").lower()
    if ptype in {"int", "float", "number"}:
        rules.append("numeric")
    if param.get("choices"):
        rules.append(f"one_of:{','.join(str(c) for c in param['choices'])}")
    return "|".join(rules) or "optional"


def validate_ui_product_integrity(project_dir: Path | str) -> dict:
    """
    Validador Anti-UI Falsa (Fase 5 y Fase 8):
    Inspecciona archivos de presentación (HTML/JS/TS/TSX/PyQt) y rechaza:
    1. Botones decorativos sin acción real conectada.
    2. Datos falsos / placeholders / simulaciones presentadas como reales.
    3. Páginas que simplemente imprimen comandos de terminal (anti-patrón CLI wrapper).
    4. Falta de accesibilidad básica o manejo de errores.
    """
    root = Path(project_dir).resolve()
    violations: list[dict] = []
    checked_files: list[str] = []
    html_texts: list[str] = []
    script_texts: list[str] = []
    pyqt_texts: list[str] = []

    for p in sorted(root.rglob("*")):
        if any(part in {".git", "node_modules", "__pycache__", ".venv", "dist", "build"} for part in p.parts):
            continue
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext not in {".html", ".js", ".ts", ".tsx", ".jsx", ".vue", ".svelte", ".py"}:
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(p.relative_to(root))
        is_ui_py = ext == ".py" and any(k in txt for k in ("PyQt6", "PySide6", "QMainWindow", "tkinter"))
        if ext == ".py" and not is_ui_py:
            continue

        checked_files.append(rel)
        if ext == ".html":
            html_texts.append((rel, txt))
        elif is_ui_py:
            pyqt_texts.append((rel, txt))
        else:
            script_texts.append((rel, txt))

        if _FAKE_DATA_RE.search(txt):
            violations.append({"file": rel, "code": "fake_or_placeholder_ui", "detail": "Se detectaron datos simulados o placeholders sin implementación real."})
        if _CLI_WRAPPER_ANTIPATTERN_RE.search(txt):
            violations.append({"file": rel, "code": "cli_command_printer_antipattern", "detail": "La interfaz imprime comandos de terminal en vez de ejecutar la lógica real."})

    combined_scripts = "\n".join(t for _, t in script_texts)

    for rel, htxt in html_texts:
        # Verificar accesibilidad básica
        if "<main" not in htxt.lower():
            violations.append({"file": rel, "code": "missing_accessibility_landmark", "detail": "Falta elemento semántico <main>."})
        # Verificar botones conectados
        for m in _DECORATIVE_BUTTON_RE.finditer(htxt):
            attrs = m.group(1) or ""
            label = re.sub(r"<[^>]+>", "", m.group(2) or "").strip()[:40]
            has_inline = bool(re.search(r"\bonclick\s*=|\btype\s*=\s*['\"]submit['\"]|\btype\s*=\s*['\"]reset['\"]", attrs, re.IGNORECASE))
            id_m = re.search(r"\bid\s*=\s*['\"]([^'\"]+)['\"]", attrs, re.IGNORECASE)
            nav_m = re.search(r"\bdata-(?:nav|action|view)\s*=\s*['\"]([^'\"]+)['\"]", attrs, re.IGNORECASE)
            bound_in_js = False
            if id_m and id_m.group(1) in combined_scripts:
                bound_in_js = True
            if nav_m and ("data-nav" in combined_scripts or "data-action" in combined_scripts or "data-view" in combined_scripts):
                bound_in_js = True
            if not (has_inline or bound_in_js):
                violations.append(
                    {
                        "file": rel,
                        "code": "decorative_unwired_button",
                        "detail": f"Botón sin acción conectada: '{label or attrs.strip()[:30]}'",
                    }
                )

        # Verificar conexión real con API/backend en scripts si hay HTML interactivo
        if html_texts and script_texts:
            if not re.search(r"\bfetch\s*\(|\bWebSocket\s*\(|\baxios\.|\bXMLHttpRequest", combined_scripts):
                violations.append(
                    {
                        "file": rel,
                        "code": "unwired_frontend_no_api_call",
                        "detail": "El frontend no realiza llamadas reales a API ni WebSocket.",
                    }
                )

    for rel, ptxt in pyqt_texts:
        if "QPushButton" in ptxt and ".clicked.connect(" not in ptxt:
            violations.append(
                {
                    "file": rel,
                    "code": "decorative_unwired_qt_button",
                    "detail": "QPushButton declarado sin señal .clicked.connect(...) conectada a lógica real.",
                }
            )

    if not checked_files:
        violations.append({"file": str(root), "code": "no_ui_files_found", "detail": "No se encontraron archivos de interfaz gráfica para validar."})

    return {
        "ok": len(violations) == 0,
        "checked_files": checked_files,
        "violations_count": len(violations),
        "violations": violations,
    }
