#!/usr/bin/env python3
"""
Adaptador Desacoplado DeepSeek Harness vía ACP (Agent Client Protocol) — OpenCode-Saghet (Fase 5).

Reglas obligatorias aplicadas:
1. OpenCode continúa siendo el motor principal de programación.
2. Gentle AI conserva el control de selección y enrutamiento (classify_and_route + SmartModelRouter).
3. Harness coordina workflows complejos cuando aporte valor.
4. Prohibido incorporar Cordis dentro del núcleo de OpenCode (cordis_in_core = False).
5. Prohibido duplicar gestión de agentes, sesiones o memoria (reutiliza agentes OpenCode,
   opencode.db session_v2 y HierarchicalMemoryStore).
6. Posibilidad de desactivar Harness en cualquier momento (config/harness.json o SAGHET_HARNESS_ENABLED=0).
7. Contratos y protocolos documentados (ACP JSON-RPC 2.0 sobre stdio).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from scripts.supervisor.gentle_ai_bridge import classify_and_route

_PROMPT_INJECTION_RE = re.compile(
    r"(?i)(ignore\s+(?:all\s+)?previous\s+instructions|override\s+allowlist|"
    r"disable\s+security|reveal\s+system\s+prompt|rm\s+-rf\s+/)"
)


def sanitize_untrusted_content(text: str) -> dict:
    """
    Trata archivos, repositorios y respuestas de herramientas como datos no confiables,
    detectando y neutralizando intentos de prompt injection.
    """
    raw = text or ""
    hits = _PROMPT_INJECTION_RE.findall(raw)
    sanitized = _PROMPT_INJECTION_RE.sub("[BLOCKED_UNTRUSTED_INSTRUCTION]", raw)
    return {
        "injection_detected": bool(hits),
        "matches": hits[:5],
        "sanitized_text": sanitized,
    }

REPO_DIR = Path(__file__).resolve().parent.parent.parent
HARNESS_CONFIG_PATH = REPO_DIR / "config" / "harness.json"
OPENCODE_CONFIG_DIR = Path.home() / ".config" / "opencode"
USER_HARNESS_CONFIG_PATH = OPENCODE_CONFIG_DIR / "harness.json"
OPENCODE_BIN = "/usr/bin/opencode" if Path("/usr/bin/opencode").is_file() else (shutil.which("opencode") or "opencode")

ACP_METHODS = (
    "initialize",
    "session/new",
    "session/load",
    "session/prompt",
    "session/cancel",
    "subagent/delegate",
    "workflow/event",
)


def load_harness_config() -> dict:
    """Carga la configuración declarativa del adaptador Harness respetando override de usuario y entorno."""
    cfg: dict = {}
    for candidate in (USER_HARNESS_CONFIG_PATH, HARNESS_CONFIG_PATH):
        if candidate.is_file():
            try:
                cfg = json.loads(candidate.read_text(encoding="utf-8"))
                break
            except Exception:
                continue

    if not cfg:
        cfg = {
            "schema": "saghet.deepseek-harness-adapter/v1",
            "enabled": True,
            "cordis_in_core": False,
            "duplicate_state_stores": False,
        }

    # Garantías inmutables de arquitectura
    cfg["cordis_in_core"] = False
    cfg["duplicate_state_stores"] = False

    env_flag = os.environ.get("SAGHET_HARNESS_ENABLED", "").strip().lower()
    if env_flag in {"0", "false", "no", "off"}:
        cfg["enabled"] = False
    elif env_flag in {"1", "true", "yes", "on"}:
        cfg["enabled"] = True

    return cfg


def set_harness_enabled(enabled: bool, persist_user_config: bool = True) -> dict:
    """Permite activar o desactivar el adaptador Harness sin tocar el núcleo de OpenCode."""
    cfg = load_harness_config()
    cfg["enabled"] = bool(enabled)
    cfg["cordis_in_core"] = False
    if persist_user_config:
        try:
            OPENCODE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            USER_HARNESS_CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            pass
    return cfg


class ACPContract:
    """
    Contrato tipado para tramas JSON-RPC 2.0 del protocolo ACP (Agent Client Protocol)
    entre el coordinador de workflows (DeepSeek Harness / Saghet DAG) y OpenCode ACP.
    """

    @staticmethod
    def build_request(method: str, params: dict, req_id: str | int | None = None) -> dict:
        if method not in ACP_METHODS:
            raise ValueError(f"Método ACP no soportado en contrato: {method}")
        return {
            "jsonrpc": "2.0",
            "id": req_id if req_id is not None else f"acp_{uuid.uuid4().hex[:10]}",
            "method": method,
            "params": params,
        }

    @staticmethod
    def build_notification(method: str, params: dict) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

    @staticmethod
    def build_response(req_id: str | int, result: dict) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result,
        }

    @staticmethod
    def build_error(req_id: str | int | None, code: int, message: str, data: dict | None = None) -> dict:
        err: dict = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": err,
        }

    @staticmethod
    def validate_frame(frame: dict) -> tuple[bool, str]:
        if not isinstance(frame, dict) or frame.get("jsonrpc") != "2.0":
            return False, "Trama inválida: falta jsonrpc == '2.0'"
        if "method" in frame:
            if not isinstance(frame.get("params"), dict):
                return False, "Trama de petición/notificación ACP requiere objeto 'params'"
            return True, "OK"
        if "result" in frame or "error" in frame:
            if "id" not in frame:
                return False, "Trama de respuesta ACP requiere 'id'"
            return True, "OK"
        return False, "Trama JSON-RPC incompleta"


class DecoupledACPAdapter:
    """
    Adaptador desacoplado que conecta workflows complejos con OpenCode ACP (`opencode acp`)
    y conserva a Gentle AI como única autoridad de selección de modelo y especialista.
    """

    def __init__(self) -> None:
        self.config = load_harness_config()

    def is_enabled(self) -> bool:
        return bool(load_harness_config().get("enabled", True))

    def probe_opencode_acp_support(self) -> dict:
        """Verifica que el binario de OpenCode soporte nativamente el servidor ACP (`opencode acp`)."""
        try:
            res = subprocess.run(
                [OPENCODE_BIN, "acp", "--help"],
                capture_output=True,
                text=True,
                timeout=4.0,
                check=False,
            )
            supported = res.returncode == 0 and "Agent Client Protocol" in (res.stdout + res.stderr)
            return {
                "opencode_acp_available": supported,
                "binary": OPENCODE_BIN,
                "protocol": "jsonrpc-2.0-stdio",
            }
        except Exception as exc:
            return {
                "opencode_acp_available": False,
                "binary": OPENCODE_BIN,
                "error": str(exc),
            }

    def prepare_subagent_delegation(
        self,
        task_id: str,
        objective: str,
        directory: str,
        persistent_session_id: str | None = None,
        preferred_specialist: str | None = None,
    ) -> dict:
        """
        Prepara una delegación de subagente mediada por Gentle AI.
        Si Harness está desactivado, devuelve un sobre de ejecución directa sobre OpenCode nativo.
        Si Harness está activado, construye la trama ACP JSON-RPC 2.0 validada por contrato.
        """
        # Gentle AI conserva SIEMPRE el control de clasificación y selección de modelo
        routing = classify_and_route(objective)
        specialist = preferred_specialist or routing["primary_specialist"]
        model = routing["selected_model"]
        session_id = persistent_session_id or f"sess_{uuid.uuid4().hex[:12]}"

        if not self.is_enabled():
            return {
                "mode": "native_opencode_fallback",
                "harness_enabled": False,
                "task_id": task_id,
                "session_id": session_id,
                "specialist": specialist,
                "model": model,
                "fallback_chain": routing.get("fallback_chain", []),
                "directory": directory,
                "routing": routing,
            }

        acp_request = ACPContract.build_request(
            method="subagent/delegate",
            params={
                "task_id": task_id,
                "session_id": session_id,
                "engine": "opencode",
                "router": "gentle-ai-4.5.0",
                "agent": specialist,
                "model": model,
                "fallback_chain": routing.get("fallback_chain", []),
                "cwd": directory,
                "prompt": objective,
                "vram_policy": "sequential_single_model_8gb",
            },
        )
        valid, reason = ACPContract.validate_frame(acp_request)
        if not valid:
            raise RuntimeError(reason)

        return {
            "mode": "harness_acp_jsonrpc",
            "harness_enabled": True,
            "task_id": task_id,
            "session_id": session_id,
            "specialist": specialist,
            "model": model,
            "fallback_chain": routing.get("fallback_chain", []),
            "directory": directory,
            "acp_frame": acp_request,
            "routing": routing,
        }

    def execute_acp_stdio(self, request_frame: dict, cwd: str | None = None, timeout_s: float = 15.0) -> dict:
        """
        Ejecuta una trama ACP JSON-RPC 2.0 real contra `opencode acp` vía stdio.
        Nunca simula éxito si el proceso falla o no responde JSON-RPC válido.
        """
        valid, reason = ACPContract.validate_frame(request_frame)
        if not valid:
            return {"ok": False, "error": f"Trama ACP inválida: {reason}"}

        payload_line = json.dumps(request_frame, ensure_ascii=False) + "\n"
        try:
            res = subprocess.run(
                [OPENCODE_BIN, "acp"],
                input=payload_line,
                cwd=cwd or str(REPO_DIR),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except Exception as exc:
            return {"ok": False, "error": f"Fallo ejecutando opencode acp: {exc}"}

        for line in res.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                frame = json.loads(line)
                ok_frame, _ = ACPContract.validate_frame(frame)
                if ok_frame:
                    return {"ok": "error" not in frame, "frame": frame, "returncode": res.returncode}
            except Exception:
                continue

        return {
            "ok": False,
            "returncode": res.returncode,
            "error": (res.stderr or res.stdout or "Sin respuesta JSON-RPC 2.0 de opencode acp").strip()[:400],
        }

    def get_status(self) -> dict:
        cfg = load_harness_config()
        acp_probe = self.probe_opencode_acp_support()
        return {
            "enabled": bool(cfg.get("enabled", True)),
            "cordis_in_core": False,
            "duplicate_state_stores": False,
            "engine_hierarchy": cfg.get("engine_hierarchy"),
            "acp_probe": acp_probe,
            "vram_guard": cfg.get("vram_guard"),
            "capabilities": cfg.get("capabilities", []),
        }
