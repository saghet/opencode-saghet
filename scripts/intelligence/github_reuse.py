#!/usr/bin/env python3
"""
GitHub Reuse Intelligence Engine — OpenCode-Saghet (Fase 3 / v0.5.0).

Motor especializado para investigar, auditar y reutilizar de forma segura proyectos
y componentes de GitHub sin copiar repositorios indiscriminadamente ni ejecutar jamás
scripts de código externo no confiable.

Flujo obligatorio (10 pasos):
1. Comprender funcionalidad requerida y stack objetivo.
2. Buscar repositorios y código similar (`gh` CLI / GitHub REST API).
3. Identificar bibliotecas y componentes aprovechables.
4. Clonar/inspeccionar en sandbox aislado (`core.hooksPath=/dev/null`, `core.symlinks=false`, 0 ejecución).
5. Analizar arquitectura vía `SemanticProjectEngine`.
6. Identificar funciones/módulos reutilizables (sin copia masiva).
7. Evaluar compatibilidad tecnológica.
8. Comprobar licencia SPDX, compatibilidad y obligaciones de atribución.
9. Auditar seguridad, scripts de instalación y prompt injection.
10. Emitir Informe de Reutilización (`reuse_as_dependency` | `adapt_selected_components` | `build_from_scratch`).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from scripts.intelligence.semantic_engine import SemanticProjectEngine

# Matriz de licencias SPDX y compatibilidad con proyectos MIT/permisivos (como OpenCode-Saghet)
LICENSE_MATRIX: dict[str, dict] = {
    "MIT": {"category": "permissive", "compatible_with_mit": True, "copyleft": False, "obligations": ["Conservar aviso de copyright y texto de licencia MIT en NOTICE.md / LICENSE."]},
    "Apache-2.0": {"category": "permissive", "compatible_with_mit": True, "copyleft": False, "obligations": ["Conservar licencia Apache-2.0, archivo NOTICE si existe y documentar modificaciones."]},
    "BSD-2-Clause": {"category": "permissive", "compatible_with_mit": True, "copyleft": False, "obligations": ["Conservar aviso de copyright y cláusulas BSD-2."]},
    "BSD-3-Clause": {"category": "permissive", "compatible_with_mit": True, "copyleft": False, "obligations": ["Conservar aviso de copyright y cláusula de no respaldo BSD-3."]},
    "ISC": {"category": "permissive", "compatible_with_mit": True, "copyleft": False, "obligations": ["Conservar aviso de copyright y licencia ISC."]},
    "Unlicense": {"category": "public_domain", "compatible_with_mit": True, "copyleft": False, "obligations": ["Sin obligaciones legales; se recomienda registrar procedencia."]},
    "MPL-2.0": {"category": "weak_copyleft", "compatible_with_mit": True, "copyleft": True, "obligations": ["Archivos modificados de MPL-2.0 deben mantenerse bajo MPL-2.0 y publicarse sus fuentes."]},
    "LGPL-2.1": {"category": "weak_copyleft", "compatible_with_mit": True, "copyleft": True, "obligations": ["Usar preferiblemente como biblioteca enlazada; cambios a la librería requieren LGPL-2.1."]},
    "LGPL-3.0": {"category": "weak_copyleft", "compatible_with_mit": True, "copyleft": True, "obligations": ["Usar preferiblemente como biblioteca enlazada; cambios a la librería requieren LGPL-3.0."]},
    "GPL-2.0": {"category": "strong_copyleft", "compatible_with_mit": False, "copyleft": True, "obligations": ["Copyleft fuerte: integrar código fuente obliga a licenciar obra derivada bajo GPL-2.0."]},
    "GPL-3.0": {"category": "strong_copyleft", "compatible_with_mit": False, "copyleft": True, "obligations": ["Copyleft fuerte: integrar código fuente obliga a licenciar obra derivada bajo GPL-3.0."]},
    "AGPL-3.0": {"category": "network_copyleft", "compatible_with_mit": False, "copyleft": True, "obligations": ["Copyleft de red: prohibido copiar código en núcleo MIT; solo admisible como plugin/servicio aislado."]},
    "UNKNOWN": {"category": "unknown", "compatible_with_mit": False, "copyleft": False, "obligations": ["Licencia no identificada: prohibido copiar código hasta confirmar permisos legales."]},
}

_SECURITY_STATIC_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("critical", "remote_shell_pipe", re.compile(r"(?:curl|wget)\s+[^\n|]{4,160}\|\s*(?:sh|bash|zsh)", re.IGNORECASE)),
    ("high", "dynamic_code_exec", re.compile(r"\b(?:eval|exec)\s*\(|__import__\s*\(|subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True", re.IGNORECASE)),
    ("high", "obfuscated_payload", re.compile(r"base64\.(?:b64decode|decodebytes)|atob\(|fromCharCode\(", re.IGNORECASE)),
    ("high", "prompt_injection_embedded", re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions|override\s+system\s+prompt|exfiltrate\s+(?:secrets|keys|env)", re.IGNORECASE)),
    ("medium", "os_system_call", re.compile(r"\bos\.system\s*\(|\bos\.popen\s*\(", re.IGNORECASE)),
)


def detect_license_in_directory(repo_dir: Path, hinted_spdx: str = "") -> dict:
    """Detecta la licencia SPDX de un repositorio inspeccionado y evalúa compatibilidad."""
    spdx = (hinted_spdx or "").strip()
    license_file_found: str | None = None
    text = ""
    for cand in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "LICENCE"):
        p = repo_dir / cand
        if p.is_file():
            license_file_found = cand
            try:
                text = p.read_text(encoding="utf-8", errors="replace")[:5000]
            except OSError:
                text = ""
            break

    if not spdx or spdx.upper() in {"NOASSERTION", "OTHER", "UNKNOWN"}:
        low = text.lower()
        if "gnu affero general public license" in low:
            spdx = "AGPL-3.0"
        elif "gnu general public license" in low and "version 3" in low:
            spdx = "GPL-3.0"
        elif "gnu general public license" in low and "version 2" in low:
            spdx = "GPL-2.0"
        elif "gnu lesser general public license" in low:
            spdx = "LGPL-3.0" if "version 3" in low else "LGPL-2.1"
        elif "mozilla public license" in low:
            spdx = "MPL-2.0"
        elif "apache license" in low and "version 2.0" in low:
            spdx = "Apache-2.0"
        elif "permission is hereby granted, free of charge" in low or "mit license" in low:
            spdx = "MIT"
        elif "redistribution and use in source and binary forms" in low:
            spdx = "BSD-3-Clause" if ("neither the name of" in low or "endorse or promote" in low) else "BSD-2-Clause"
        elif "isc license" in low:
            spdx = "ISC"
        elif "this is free and unencumbered software released into the public domain" in low:
            spdx = "Unlicense"
        else:
            spdx = "UNKNOWN"

    norm_spdx = spdx if spdx in LICENSE_MATRIX else "UNKNOWN"
    info = LICENSE_MATRIX[norm_spdx]
    return {
        "spdx": norm_spdx,
        "raw_detected": spdx,
        "license_file": license_file_found,
        **info,
    }


def scan_untrusted_repository_security(repo_dir: Path, max_files: int = 120) -> dict:
    """
    Escaneo estático de seguridad sobre un repositorio externo no confiable.
    NUNCA ejecuta código ni scripts del repositorio.
    """
    findings: list[dict] = []
    suspicious_install_hooks: list[str] = []
    scanned = 0

    pkg_json = repo_dir / "package.json"
    if pkg_json.is_file():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
            scripts = pkg.get("scripts") or {}
            for hook in ("preinstall", "install", "postinstall", "prepare"):
                if hook in scripts:
                    suspicious_install_hooks.append(f"package.json:scripts.{hook}={str(scripts[hook])[:120]}")
        except Exception:
            pass

    setup_py = repo_dir / "setup.py"
    if setup_py.is_file():
        try:
            stxt = setup_py.read_text(encoding="utf-8", errors="replace")[:4000]
            if re.search(r"subprocess|os\.system|urllib|requests\.get", stxt):
                suspicious_install_hooks.append("setup.py contiene llamadas de sistema o red durante instalación")
        except OSError:
            pass

    for path in sorted(repo_dir.rglob("*")):
        if scanned >= max_files:
            break
        if any(part in {".git", "node_modules", "__pycache__", ".venv", "dist", "build"} for part in path.parts):
            continue
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".sh", ".md", ".json", ".toml", ".yaml", ".yml", ".rs", ".go"}:
            continue
        try:
            if path.stat().st_size > 256 * 1024:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned += 1
        rel = str(path.relative_to(repo_dir))
        for sev, rule_id, pat in _SECURITY_STATIC_RULES:
            if pat.search(text):
                findings.append({"severity": sev, "rule": rule_id, "file": rel})
                if len(findings) >= 40:
                    break

    critical_count = sum(1 for f in findings if f["severity"] == "critical")
    high_count = sum(1 for f in findings if f["severity"] == "high")
    risk_level = "critical" if critical_count > 0 else ("high" if (high_count >= 2 or suspicious_install_hooks) else ("medium" if findings else "low"))
    return {
        "executed_external_code": False,
        "files_scanned": scanned,
        "risk_level": risk_level,
        "suspicious_install_hooks": suspicious_install_hooks,
        "findings": findings[:25],
    }


class GitHubReuseEngine:
    """
    Motor de Investigación y Reutilización Segura de Código en GitHub (Fase 3).
    """

    def __init__(
        self,
        semantic_engine: SemanticProjectEngine | None = None,
        sandbox_root: Path | None = None,
    ) -> None:
        self.semantic = semantic_engine or SemanticProjectEngine()
        self.sandbox_root = Path(sandbox_root) if sandbox_root else None
        self.gh_bin = shutil.which("gh")
        self.git_bin = shutil.which("git") or "git"

    def search_repositories(self, query: str, language: str | None = None, limit: int = 5) -> dict:
        """Busca repositorios en GitHub usando `gh search repos` o GitHub REST API pública."""
        q = (query or "").strip()
        if not q:
            return {"ok": False, "error": "Consulta de búsqueda vacía", "repositories": []}

        # 1. Intentar vía gh CLI autenticado (sin límites estrictos anónimos)
        if self.gh_bin:
            cmd = [
                self.gh_bin,
                "search",
                "repos",
                q,
                "--limit",
                str(max(1, min(15, limit))),
                "--json",
                "fullName,description,url,stargazersCount,language,license,updatedAt",
            ]
            if language:
                cmd.extend(["--language", language])
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=12.0, check=False)
                if res.returncode == 0 and res.stdout.strip():
                    items = json.loads(res.stdout)
                    repos = [
                        {
                            "full_name": it.get("fullName"),
                            "description": it.get("description") or "",
                            "url": it.get("url"),
                            "stars": int(it.get("stargazersCount") or 0),
                            "language": it.get("language") or "",
                            "license": (it.get("license") or {}).get("key") or (it.get("license") or {}).get("name") or "UNKNOWN",
                            "updated_at": it.get("updatedAt") or "",
                        }
                        for it in items
                    ]
                    return {"ok": True, "source": "gh_cli", "query": q, "repositories": repos}
            except Exception:
                pass

        # 2. Fallback a GitHub REST API pública
        search_q = f"{q} language:{language}" if language else q
        url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(search_q)}&sort=stars&per_page={max(1, min(15, limit))}"
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "OpenCode-Saghet/0.5.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            repos = [
                {
                    "full_name": it.get("full_name"),
                    "description": it.get("description") or "",
                    "url": it.get("html_url"),
                    "stars": int(it.get("stargazers_count") or 0),
                    "language": it.get("language") or "",
                    "license": (it.get("license") or {}).get("spdx_id") or "UNKNOWN",
                    "updated_at": it.get("updated_at") or "",
                }
                for it in (data.get("items") or [])
            ]
            return {"ok": True, "source": "github_rest_api", "query": q, "repositories": repos}
        except Exception as exc:
            return {"ok": False, "source": "offline_or_error", "error": str(exc), "repositories": []}

    def search_code(self, query: str, language: str | None = None, limit: int = 5) -> dict:
        """Busca fragmentos de código en GitHub mediante `gh search code`."""
        q = (query or "").strip()
        if not q or not self.gh_bin:
            return {"ok": False, "error": "Requiere gh CLI autenticado y consulta no vacía", "matches": []}
        cmd = [
            self.gh_bin,
            "search",
            "code",
            q,
            "--limit",
            str(max(1, min(15, limit))),
            "--json",
            "path,repository,url",
        ]
        if language:
            cmd.extend(["--language", language])
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=12.0, check=False)
            if res.returncode == 0 and res.stdout.strip():
                raw = json.loads(res.stdout)
                matches = [
                    {
                        "repository": (it.get("repository") or {}).get("nameWithOwner"),
                        "path": it.get("path"),
                        "url": it.get("url"),
                    }
                    for it in raw
                ]
                return {"ok": True, "source": "gh_search_code", "matches": matches}
            return {"ok": False, "error": (res.stderr or res.stdout).strip()[:300], "matches": []}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "matches": []}

    def clone_safely_for_inspection(self, repo_url_or_path: str, dest_dir: Path) -> dict:
        """
        Clona de forma superficial y segura un repositorio (remoto HTTPS o ruta git local)
        desactivando hooks y symlinks para impedir ejecución automática.
        """
        target = (repo_url_or_path or "").strip()
        if not target:
            return {"ok": False, "error": "URL o ruta de repositorio vacía"}
        if not (target.startswith("https://github.com/") or Path(target).is_dir()):
            return {"ok": False, "error": "Solo se permiten repositorios HTTPS de GitHub o directorios locales verificados."}

        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.git_bin,
            "clone",
            "--depth",
            "1",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.symlinks=false",
            target,
            str(dest_dir),
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=35.0, check=False)
            if res.returncode != 0:
                return {"ok": False, "error": (res.stderr or res.stdout).strip()[:400]}
            return {"ok": True, "inspected_dir": str(dest_dir), "executed_external_code": False}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def inspect_and_generate_reuse_report(
        self,
        repo_path_or_url: str,
        needed_functionality: str,
        target_language: str = "Python",
        target_license: str = "MIT",
        hinted_spdx: str = "",
    ) -> dict:
        """
        Ejecuta los pasos 4–10 del flujo obligatorio y genera el Informe de Reutilización estructurado.
        """
        tmp_ctx = None
        source_ref = repo_path_or_url
        try:
            local_cand = Path(repo_path_or_url)
            if local_cand.is_dir():
                inspect_dir = local_cand.resolve()
            else:
                tmp_ctx = tempfile.TemporaryDirectory(prefix="saghet_gh_inspect_", dir=self.sandbox_root)
                inspect_dir = Path(tmp_ctx.name) / "repo"
                clone_res = self.clone_safely_for_inspection(repo_path_or_url, inspect_dir)
                if not clone_res.get("ok"):
                    return {"ok": False, "source_repository": source_ref, "error": clone_res.get("error")}

            # Paso 5 & 6: Análisis arquitectónico y componentes reutilizables
            sem_db = inspect_dir.parent / ".saghet_inspect_index.db" if tmp_ctx else None
            sem_eng = SemanticProjectEngine(db_path=sem_db) if sem_db else self.semantic
            analysis = sem_eng.analyze_codebase(inspect_dir)
            if not analysis.get("ok"):
                return {"ok": False, "source_repository": source_ref, "error": analysis.get("error")}

            ci = analysis["codebase_intelligence"]
            # Paso 8: Licencia SPDX y compatibilidad
            lic = detect_license_in_directory(inspect_dir, hinted_spdx=hinted_spdx)
            # Paso 9: Auditoría estática de seguridad (0 ejecución)
            sec = scan_untrusted_repository_security(inspect_dir)

            # Paso 7: Evaluación de compatibilidad tecnológica
            primary_lang = ci["primary_language"]
            lang_match = primary_lang.lower() == target_language.lower() or any(
                l["language"].lower() == target_language.lower() for l in ci["languages"]
            )
            compatibility = {
                "target_language": target_language,
                "repo_primary_language": primary_lang,
                "language_compatible": lang_match,
                "frameworks_detected": ci["frameworks"],
                "license_compatible": bool(lic["compatible_with_mit"]) if target_license.upper() == "MIT" else True,
            }

            # Filtrar componentes relevantes a la funcionalidad solicitada (sin copiar todo el repo)
            need_tokens = {t.lower() for t in re.findall(r"[A-Za-z0-9_]{3,}", needed_functionality or "")}
            all_reusable = ci.get("reusable_components") or []
            matched_components = []
            for comp in all_reusable:
                hay = f"{comp['symbol']} {comp['file']}".lower()
                hits = sum(1 for tok in need_tokens if tok in hay)
                matched_components.append({**comp, "relevance_hits": hits})
            matched_components.sort(key=lambda c: (c["relevance_hits"], 1 if c["decoupled_from_ui"] else 0, c["in_degree"]), reverse=True)
            selected_components = matched_components[:10]

            # Riesgos y ventajas
            risks: list[str] = []
            advantages: list[str] = []
            if not compatibility["license_compatible"]:
                risks.append(f"Licencia incompatible ({lic['spdx']}): {', '.join(lic['obligations'])}")
            if sec["risk_level"] in {"critical", "high"}:
                risks.append(f"Riesgo de seguridad estática {sec['risk_level']} ({len(sec['findings'])} hallazgos, {len(sec['suspicious_install_hooks'])} hooks sospechosos).")
            if not lang_match:
                risks.append(f"Diferencia de lenguaje: repositorio en {primary_lang} vs destino en {target_language}.")
            if ci.get("circular_dependencies"):
                risks.append(f"Dependencias circulares detectadas ({len(ci['circular_dependencies'])}).")

            if compatibility["license_compatible"]:
                advantages.append(f"Licencia {lic['spdx']} ({lic['category']}) compatible con {target_license}.")
            if selected_components:
                advantages.append(f"{len(selected_components)} componentes desacoplados identificados sin necesidad de copiar el repositorio completo.")
            if lang_match:
                advantages.append(f"Compatible nativamente con el stack objetivo ({target_language}).")

            # Paso 10: Decisión estratégica
            has_package_manifest = any((inspect_dir / m).is_file() for m in ("pyproject.toml", "setup.py", "package.json", "Cargo.toml", "go.mod"))
            if sec["risk_level"] == "critical" or not compatibility["license_compatible"]:
                recommendation = "build_from_scratch"
                strategy = (
                    "No integrar ni copiar código del repositorio debido a incompatibilidad de licencia o riesgo crítico de seguridad. "
                    "Diseñar e implementar solución limpia propia inspirada únicamente en requisitos funcionales."
                )
            elif lang_match and has_package_manifest and sec["risk_level"] == "low":
                recommendation = "reuse_as_dependency"
                strategy = (
                    "Instalar como dependencia fijada por versión tras revisar dependencias transitivas, "
                    "envolviéndola detrás de un adaptador local y registrando atribución en NOTICE.md."
                )
            elif selected_components and sec["risk_level"] in {"low", "medium"}:
                recommendation = "adapt_selected_components"
                strategy = (
                    "Adaptar únicamente los componentes desacoplados seleccionados (nunca copiar el repositorio completo), "
                    "preservar cabecera de copyright/licencia original en NOTICE.md y cubrir con pruebas unitarias locales."
                )
            else:
                recommendation = "build_from_scratch"
                strategy = "Desarrollar desde cero en el dominio local por baja afinidad arquitectónica o falta de componentes desacoplados."

            attribution_notice = (
                f"Source: {source_ref} | License: {lic['spdx']} | Obligations: {'; '.join(lic['obligations'])}"
            )

            return {
                "ok": True,
                "source_repository": source_ref,
                "needed_functionality": needed_functionality,
                "license": lic,
                "security_audit": sec,
                "identified_components": selected_components,
                "dependencies": ci.get("external_dependencies", {}),
                "compatibility": compatibility,
                "risks": risks,
                "advantages": advantages,
                "recommendation": recommendation,
                "integration_strategy": strategy,
                "attribution_notice": attribution_notice,
                "context7_doc_hint": f"Consultar documentación oficial vía MCP Context7 para: {', '.join(ci['frameworks'][:4]) or primary_lang}",
            }
        finally:
            if tmp_ctx is not None:
                tmp_ctx.cleanup()
