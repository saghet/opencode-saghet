#!/usr/bin/env python3
"""
Gemini 4 Neon Intelligence Core — OpenCode-Saghet (Fase 1 / v0.5.0).

Arquitectura de coordinación inteligente sobre el proveedor oficial Google Gemini API
(`gemini-4-neon`), preservando OpenCode v2.3.2 como motor de ejecución, Gentle AI 4.5.0
como metodología/memoria y Ollama local (RTX 4060 8 GB) como capa local-first y fallback.

Capacidades:
1. Integración oficial Gemini API (`https://generativelanguage.googleapis.com/v1beta`).
2. Verificación dinámica del identificador exacto de modelo disponible (`GET /v1beta/models`).
3. Conmutación dinámica de modelo y proveedor sin alterar el núcleo.
4. Control de cuotas, límites de tasa, reintentos exponenciales (429/500/503) y fallback explícito.
5. Ensamblado selectivo de contexto (nunca vuelca indiscriminadamente todo el repositorio).
6. Coordinador de propiedad de archivos (`FileOwnershipCoordinator`) anti-tareas contradictorias.
7. Bitácora auditable de decisiones, herramientas utilizadas y resultados (`0600`, sin secretos).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from scripts.eval.model_lab import SmartModelRouter
from scripts.memory.hierarchical_memory import HierarchicalMemoryStore, contains_sensitive_secret

SAGHET_STATE_DIR = Path.home() / ".local" / "share" / "opencode-saghet"
GEMINI_DECISIONS_LOG = SAGHET_STATE_DIR / "gemini_decisions.jsonl"

OFFICIAL_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_COORDINATOR_MODEL = "google/gemini-4-neon"
DEFAULT_LOCAL_FALLBACK_MODEL = "ollama/qwen3.5:9b"

# Catálogo de identificadores oficiales verificados de la familia Gemini 4 (Google Gemini API)
OFFICIAL_GEMINI_MODELS: dict[str, dict] = {
    "gemini-4-neon": {
        "provider": "google",
        "opencode_id": "google/gemini-4-neon",
        "display_name": "Gemini 4 Neon",
        "role": "primary_coordinator_architect",
        "context_tokens": 1_048_576,
        "output_tokens": 65_536,
        "supports_tools": True,
        "supports_thinking": True,
        "thinking_levels": ("low", "medium", "high", "xhigh"),
        "default_thinking_level": "high",
    },
    "gemini-4-carbon": {
        "provider": "google",
        "opencode_id": "google/gemini-4-carbon",
        "display_name": "Gemini 4 Carbon",
        "role": "reasoning_all_rounder",
        "context_tokens": 1_048_576,
        "output_tokens": 65_536,
        "supports_tools": True,
        "supports_thinking": True,
        "thinking_levels": ("low", "medium", "high"),
        "default_thinking_level": "high",
    },
    "gemini-4-hydrogen": {
        "provider": "google",
        "opencode_id": "google/gemini-4-hydrogen",
        "display_name": "Gemini 4 Hydrogen",
        "role": "fast_triage_and_classification",
        "context_tokens": 1_048_576,
        "output_tokens": 65_536,
        "supports_tools": True,
        "supports_thinking": True,
        "thinking_levels": ("low", "medium"),
        "default_thinking_level": "low",
    },
    "gemini-4-argon": {
        "provider": "google",
        "opencode_id": "google/gemini-4-argon",
        "display_name": "Gemini 4 Argon",
        "role": "frontier_coding_and_security",
        "context_tokens": 1_048_576,
        "output_tokens": 65_536,
        "supports_tools": True,
        "supports_thinking": True,
        "thinking_levels": ("low", "medium", "high"),
        "default_thinking_level": "high",
    },
}

_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
_SECRET_REDACT_RE = re.compile(
    r"(?i)((?:key|api[_-]?key|token|authorization)\s*[=:]\s*)([^\s&\"']+)|(AIza[0-9A-Za-z\-_]{20,})"
)


def _redact(text: str) -> str:
    if not text:
        return ""
    return _SECRET_REDACT_RE.sub(lambda m: f"{m.group(1)}[REDACTED]" if m.group(1) else "[REDACTED_API_KEY]", text)


def _strip_provider_prefix(model_id: str) -> tuple[str, str]:
    raw = (model_id or "").strip()
    if "/" in raw:
        prov, mid = raw.split("/", 1)
        return prov.strip().lower(), mid.strip()
    if raw in OFFICIAL_GEMINI_MODELS or raw.startswith("gemini-"):
        return "google", raw
    return "ollama", raw


def resolve_gemini_api_key(explicit_key: str | None = None) -> str:
    """Resuelve la clave oficial de Gemini API desde parámetro o variables estándar sin imprimirla."""
    if explicit_key and explicit_key.strip():
        return explicit_key.strip()
    for env_name in ("GEMINI_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY", "GOOGLE_API_KEY"):
        val = os.environ.get(env_name, "").strip()
        if val:
            return val
    return ""


@dataclass
class QuotaBudget:
    """Controlador de cuotas, límites por minuto y presupuesto de tokens para llamadas Gemini API."""

    max_requests_per_minute: int = 30
    max_tokens_per_session: int = 400_000
    max_context_chars_per_call: int = 120_000
    _request_timestamps: list[float] = field(default_factory=list)
    _tokens_used: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def can_consume(self, estimated_tokens: int = 0) -> tuple[bool, str]:
        now = time.monotonic()
        with self._lock:
            self._request_timestamps = [t for t in self._request_timestamps if (now - t) < 60.0]
            if len(self._request_timestamps) >= self.max_requests_per_minute:
                return False, f"rate_limit_exceeded: {len(self._request_timestamps)}/{self.max_requests_per_minute} req/min"
            if (self._tokens_used + max(0, estimated_tokens)) > self.max_tokens_per_session:
                return False, f"token_quota_exceeded: {self._tokens_used + estimated_tokens}/{self.max_tokens_per_session}"
        return True, "ok"

    def record_usage(self, tokens_used: int) -> None:
        now = time.monotonic()
        with self._lock:
            self._request_timestamps.append(now)
            self._tokens_used += max(0, int(tokens_used))

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._request_timestamps if (now - t) < 60.0]
            return {
                "requests_last_minute": len(recent),
                "max_requests_per_minute": self.max_requests_per_minute,
                "tokens_used_session": self._tokens_used,
                "max_tokens_per_session": self.max_tokens_per_session,
                "remaining_tokens": max(0, self.max_tokens_per_session - self._tokens_used),
            }


@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0
    backoff_multiplier: float = 2.0

    def delay_for_attempt(self, attempt: int) -> float:
        return min(self.max_delay_s, self.base_delay_s * (self.backoff_multiplier ** max(0, attempt - 1)))


class FileOwnershipCoordinator:
    """
    Evita que dos agentes/especialistas ejecuten tareas contradictorias o compitan
    por escribir en los mismos archivos simultáneamente.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._write_claims: dict[str, dict] = {}
        self._read_claims: dict[str, set[str]] = {}

    @staticmethod
    def _norm(path: str) -> str:
        return str(Path(path).as_posix()).lstrip("./").strip()

    def claim_files(
        self,
        task_id: str,
        specialist: str,
        write_files: list[str] | None = None,
        read_files: list[str] | None = None,
    ) -> dict:
        writes = [self._norm(p) for p in (write_files or []) if p]
        reads = [self._norm(p) for p in (read_files or []) if p]
        conflicts: list[dict] = []

        with self._lock:
            for wf in writes:
                owner = self._write_claims.get(wf)
                if owner and owner["task_id"] != task_id:
                    conflicts.append(
                        {
                            "file": wf,
                            "type": "write_write_conflict",
                            "owner_task": owner["task_id"],
                            "owner_specialist": owner["specialist"],
                        }
                    )
                readers = {t for t in self._read_claims.get(wf, set()) if t != task_id}
                if readers:
                    conflicts.append(
                        {
                            "file": wf,
                            "type": "write_while_read_conflict",
                            "active_readers": sorted(readers),
                        }
                    )
            for rf in reads:
                owner = self._write_claims.get(rf)
                if owner and owner["task_id"] != task_id:
                    conflicts.append(
                        {
                            "file": rf,
                            "type": "read_while_write_conflict",
                            "owner_task": owner["task_id"],
                            "owner_specialist": owner["specialist"],
                        }
                    )

            if conflicts:
                return {"ok": False, "task_id": task_id, "conflicts": conflicts}

            for wf in writes:
                self._write_claims[wf] = {
                    "task_id": task_id,
                    "specialist": specialist,
                    "claimed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            for rf in reads:
                self._read_claims.setdefault(rf, set()).add(task_id)

        return {"ok": True, "task_id": task_id, "claimed_writes": writes, "claimed_reads": reads}

    def release_task(self, task_id: str) -> int:
        released = 0
        with self._lock:
            for wf in [k for k, v in self._write_claims.items() if v["task_id"] == task_id]:
                self._write_claims.pop(wf, None)
                released += 1
            for rf in list(self._read_claims.keys()):
                if task_id in self._read_claims[rf]:
                    self._read_claims[rf].discard(task_id)
                    released += 1
                if not self._read_claims[rf]:
                    self._read_claims.pop(rf, None)
        return released

    def detect_plan_conflicts(self, tasks: list[dict]) -> list[dict]:
        """Detecta colisiones de escritura entre tareas sin relación de dependencia directa."""
        deps_map = {str(t.get("id")): set(t.get("dependencies") or []) for t in tasks}

        def _depends_on(a: str, b: str, seen: set[str] | None = None) -> bool:
            visited = seen or set()
            if b in deps_map.get(a, set()):
                return True
            for d in deps_map.get(a, set()):
                if d not in visited:
                    visited.add(d)
                    if _depends_on(d, b, visited):
                        return True
            return False

        conflicts: list[dict] = []
        for idx, t1 in enumerate(tasks):
            id1 = str(t1.get("id"))
            w1 = {self._norm(p) for p in (t1.get("write_files") or []) if p}
            if not w1:
                continue
            for t2 in tasks[idx + 1 :]:
                id2 = str(t2.get("id"))
                w2 = {self._norm(p) for p in (t2.get("write_files") or []) if p}
                overlap = sorted(w1 & w2)
                if overlap and not _depends_on(id1, id2) and not _depends_on(id2, id1):
                    conflicts.append(
                        {
                            "task_a": id1,
                            "task_b": id2,
                            "overlapping_files": overlap,
                            "resolution": f"Serializar '{id2}' como dependiente de '{id1}' o dividir responsabilidad de archivos.",
                        }
                    )
        return conflicts

    def active_claims(self) -> dict:
        with self._lock:
            return {
                "write_claims": dict(self._write_claims),
                "read_claims": {k: sorted(v) for k, v in self._read_claims.items()},
            }


class Gemini4NeonCoordinator:
    """
    Núcleo de Inteligencia Coordinadora bajo Gemini 4 Neon (oficial) con degradación controlada
    a Ollama local (RTX 4060 8 GB). Actúa como arquitecto y coordinador, nunca como sustituto
    del motor de ejecución OpenCode.
    """

    def __init__(
        self,
        model_id: str | None = None,
        api_key: str | None = None,
        api_base: str = OFFICIAL_GEMINI_API_BASE,
        quota: QuotaBudget | None = None,
        retry_policy: RetryPolicy | None = None,
        ledger_path: Path | None = None,
        http_opener: Callable | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        router: SmartModelRouter | None = None,
        memory_store: HierarchicalMemoryStore | None = None,
    ) -> None:
        env_model = os.environ.get("SAGHET_COORDINATOR_MODEL", "").strip()
        self.active_model = model_id or env_model or DEFAULT_COORDINATOR_MODEL
        self._api_key = resolve_gemini_api_key(api_key)
        self.api_base = api_base.rstrip("/")
        self.quota = quota or QuotaBudget()
        self.retry_policy = retry_policy or RetryPolicy()
        self.ledger_path = Path(ledger_path or GEMINI_DECISIONS_LOG)
        self._http_opener = http_opener or urllib.request.urlopen
        self._sleep = sleep_fn
        self.router = router or SmartModelRouter()
        self.memory = memory_store
        self.ownership = FileOwnershipCoordinator()
        self._verified_models_cache: list[str] | None = None
        self._ledger_lock = threading.Lock()

    def set_active_model(self, model_id: str, reason: str = "user_override") -> dict:
        """Permite cambiar el modelo coordinador en caliente sin alterar el núcleo."""
        clean = (model_id or "").strip()
        if not clean:
            return {"ok": False, "error": "model_id vacío"}
        prov, bare = _strip_provider_prefix(clean)
        if prov == "google" and bare not in OFFICIAL_GEMINI_MODELS:
            return {
                "ok": False,
                "error": f"Modelo Google no verificado en catálogo oficial: '{bare}'. Permitidos: {sorted(OFFICIAL_GEMINI_MODELS)}",
            }
        prev = self.active_model
        self.active_model = f"{prov}/{bare}"
        self.record_decision(
            action="switch_coordinator_model",
            decision=self.active_model,
            tools_used=["gemini_core.set_active_model"],
            result={"previous_model": prev, "new_model": self.active_model, "reason": reason},
        )
        return {"ok": True, "previous_model": prev, "active_model": self.active_model, "provider": prov}

    @staticmethod
    def select_model_for_specialty(specialty: str) -> str:
        """Selecciona el modelo oficial Gemini 4 óptimo por especialidad."""
        spec = (specialty or "").strip().lower()
        mapping = {
            "architecture": "google/gemini-4-neon",
            "research": "google/gemini-4-neon",
            "coordination": "google/gemini-4-neon",
            "coding": "google/gemini-4-argon",
            "debugging": "google/gemini-4-argon",
            "security_audit": "google/gemini-4-argon",
            "independent_review": "google/gemini-4-argon",
            "classification": "google/gemini-4-hydrogen",
            "memory": "google/gemini-4-hydrogen",
            "deep_reasoning": "google/gemini-4-carbon",
        }
        return mapping.get(spec, DEFAULT_COORDINATOR_MODEL)

    def has_api_key(self) -> bool:
        return bool(self._api_key)

    def get_provider_status(self, probe_remote: bool = False) -> dict:
        """Reporta el estado real del proveedor oficial Google Gemini y del fallback Ollama."""
        prov, bare = _strip_provider_prefix(self.active_model)
        meta = OFFICIAL_GEMINI_MODELS.get(bare, {})
        verified_live: bool | None = None
        available_models: list[str] = []
        probe_error: str | None = None

        if probe_remote and self.has_api_key():
            probe = self.verify_model_availability(bare)
            verified_live = probe.get("available")
            available_models = probe.get("available_models", [])
            probe_error = probe.get("error")

        fallback_route = self.router.route("architecture", avoid_vram_swap=True)
        return {
            "active_model": self.active_model,
            "provider": prov,
            "model_id": bare,
            "official_catalog_verified": bare in OFFICIAL_GEMINI_MODELS if prov == "google" else True,
            "api_endpoint": f"{self.api_base}/models/{bare}:generateContent" if prov == "google" else "http://127.0.0.1:11434/v1",
            "api_key_configured": self.has_api_key(),
            "mode": "gemini_cloud_coordinator" if (prov == "google" and self.has_api_key()) else "local_ollama_fallback",
            "live_model_verified": verified_live,
            "available_remote_models": available_models[:15],
            "probe_error": probe_error,
            "context_tokens": meta.get("context_tokens", 22528),
            "output_tokens": meta.get("output_tokens", 2560),
            "fallback_local_model": fallback_route["selected_model"],
            "quota": self.quota.snapshot(),
        }

    def verify_model_availability(self, model_name: str = "gemini-4-neon", timeout_s: float = 6.0) -> dict:
        """
        Consulta el endpoint oficial `GET /v1beta/models` de Gemini API para verificar
        si el identificador exacto del modelo está disponible para la API key activa.
        """
        _, bare = _strip_provider_prefix(model_name)
        if not self.has_api_key():
            return {
                "ok": False,
                "available": False,
                "model": bare,
                "reason": "api_key_not_configured",
                "available_models": [],
            }
        url = f"{self.api_base}/models?key={urllib.parse.quote(self._api_key)}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with self._http_opener(req, timeout=timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            models = [
                str(m.get("name", "")).removeprefix("models/")
                for m in (data.get("models") or [])
                if m.get("name")
            ]
            self._verified_models_cache = models
            available = bare in models
            return {
                "ok": True,
                "available": available,
                "model": bare,
                "available_models": models,
                "endpoint": f"{self.api_base}/models",
            }
        except Exception as exc:
            return {
                "ok": False,
                "available": False,
                "model": bare,
                "error": _redact(str(exc)),
                "available_models": [],
            }

    def assemble_selective_context(
        self,
        objective: str,
        project_path: Path | str | None = None,
        candidate_files: list[dict] | None = None,
        max_chars: int = 24_000,
    ) -> dict:
        """
        Aprovecha el contexto largo de Gemini mediante recuperación selectiva:
        prioriza archivos relevantes por puntaje, firmas, contratos y decisiones previas,
        nunca volcando indiscriminadamente todo el proyecto.
        """
        bounded_max = min(max(1000, int(max_chars)), self.quota.max_context_chars_per_call)
        sections: list[str] = [f"[OBJECTIVE]\n{(objective or '').strip()[:1500]}"]
        used = len(sections[0])
        included_files: list[str] = []
        skipped_files: list[str] = []

        # 1. Decisiones previas y memoria relevante
        if self.memory is not None and project_path:
            mems = self.memory.retrieve_relevant_memories(
                query=objective,
                project_path=str(project_path),
                tiers=["project", "experience", "user"],
                include_provisional=False,
                limit=6,
            )
            if mems:
                mem_block = "[PRIOR_DECISIONS_AND_MEMORY]\n" + "\n".join(
                    f"- [{m['tier']}/{m['category']}] {m['title']}: {m['content'][:220]}" for m in mems
                )
                if used + len(mem_block) + 2 <= bounded_max:
                    sections.append(mem_block)
                    used += len(mem_block) + 2

        # 2. Fragmentos de código priorizados por score (sin secretos)
        ranked = sorted(candidate_files or [], key=lambda x: float(x.get("score", 0.0)), reverse=True)
        for item in ranked:
            rel = str(item.get("rel_path") or "")
            snippet = str(item.get("snippet") or item.get("summary") or "").strip()
            if not rel or not snippet:
                continue
            if contains_sensitive_secret(snippet):
                skipped_files.append(f"{rel} (blocked:secret)")
                continue
            per_file_cap = max(800, bounded_max // max(2, min(len(ranked), 8)))
            block = f"[FILE: {rel} | score={item.get('score', 0)}]\n{snippet[:per_file_cap]}"
            if used + len(block) + 2 > bounded_max:
                skipped_files.append(f"{rel} (budget_cap)")
                continue
            sections.append(block)
            used += len(block) + 2
            included_files.append(rel)

        assembled = "\n\n".join(sections)[:bounded_max]
        return {
            "ok": True,
            "selective_retrieval": True,
            "included_files": included_files,
            "skipped_files": skipped_files,
            "chars_used": len(assembled),
            "budget_chars": bounded_max,
            "estimated_tokens": max(1, len(assembled) // 4),
            "context_text": assembled,
        }

    def generate(
        self,
        prompt: str,
        system_instruction: str = "",
        thinking_level: str = "high",
        temperature: float = 0.2,
        max_output_tokens: int = 4096,
        response_mime_type: str | None = None,
        timeout_s: float = 45.0,
        allow_local_fallback: bool = True,
    ) -> dict:
        """
        Invoca el modelo coordinador configurado (oficial `gemini-4-neon` vía Gemini API)
        con reintentos exponenciales, control de cuotas y fallback explícito a Ollama si se permite.
        """
        prov, bare = _strip_provider_prefix(self.active_model)
        est_tokens = max(1, (len(prompt or "") + len(system_instruction or "")) // 4)

        if prov == "google" and not self.has_api_key():
            res = self._fallback_response(
                reason="gemini_api_key_missing",
                prompt=prompt,
                allow_local_fallback=allow_local_fallback,
            )
            self.record_decision(
                action="coordinator_generate",
                decision=res.get("model_used", self.active_model),
                tools_used=["gemini_core.generate"],
                result={"ok": res["ok"], "fallback_used": res.get("fallback_used", False), "reason": "gemini_api_key_missing"},
            )
            return res

        can_go, quota_reason = self.quota.can_consume(est_tokens)
        if not can_go:
            res = self._fallback_response(
                reason=quota_reason,
                prompt=prompt,
                allow_local_fallback=allow_local_fallback,
            )
            self.record_decision(
                action="coordinator_generate",
                decision=res.get("model_used", self.active_model),
                tools_used=["gemini_core.generate"],
                result={"ok": res["ok"], "fallback_used": res.get("fallback_used", False), "reason": quota_reason},
            )
            return res

        if prov != "google":
            return self._call_local_ollama(bare, prompt, system_instruction, max_output_tokens)

        payload: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": float(temperature),
                "maxOutputTokens": int(max_output_tokens),
            },
        }
        model_meta = OFFICIAL_GEMINI_MODELS.get(bare, {})
        if model_meta.get("supports_thinking"):
            allowed_levels = model_meta.get("thinking_levels") or ("low", "medium", "high")
            lvl = thinking_level if thinking_level in allowed_levels else model_meta.get("default_thinking_level", "high")
            payload["generationConfig"]["thinkingConfig"] = {"thinkingLevel": lvl}
        if response_mime_type:
            payload["generationConfig"]["responseMimeType"] = response_mime_type
        if system_instruction.strip():
            payload["systemInstruction"] = {"parts": [{"text": system_instruction.strip()}]}

        url = f"{self.api_base}/models/{bare}:generateContent?key={urllib.parse.quote(self._api_key)}"
        body = json.dumps(payload).encode("utf-8")

        last_err = ""
        attempts = 0
        for attempt in range(1, self.retry_policy.max_retries + 2):
            attempts = attempt
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            try:
                t0 = time.perf_counter()
                with self._http_opener(req, timeout=timeout_s) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                text = self._extract_gemini_text(raw)
                usage = raw.get("usageMetadata") or {}
                total_toks = int(usage.get("totalTokenCount") or (est_tokens + len(text) // 4))
                self.quota.record_usage(total_toks)
                out = {
                    "ok": True,
                    "provider": "google",
                    "model_used": f"google/{bare}",
                    "text": text,
                    "attempts": attempts,
                    "elapsed_ms": elapsed_ms,
                    "usage": {
                        "prompt_tokens": int(usage.get("promptTokenCount") or est_tokens),
                        "output_tokens": int(usage.get("candidatesTokenCount") or (len(text) // 4)),
                        "total_tokens": total_toks,
                    },
                    "fallback_used": False,
                }
                self.record_decision(
                    action="coordinator_generate",
                    decision=out["model_used"],
                    tools_used=["gemini_api:generateContent"],
                    result={"ok": True, "attempts": attempts, "total_tokens": total_toks, "elapsed_ms": elapsed_ms},
                )
                return out
            except urllib.error.HTTPError as exc:
                code = exc.code
                last_err = _redact(f"HTTP {code}: {exc.reason}")
                if code in _RETRYABLE_HTTP_CODES and attempt <= self.retry_policy.max_retries:
                    self._sleep(self.retry_policy.delay_for_attempt(attempt))
                    continue
                break
            except Exception as exc:
                last_err = _redact(str(exc))
                if attempt <= self.retry_policy.max_retries:
                    self._sleep(self.retry_policy.delay_for_attempt(attempt))
                    continue
                break

        res = self._fallback_response(
            reason=f"gemini_api_error:{last_err}",
            prompt=prompt,
            allow_local_fallback=allow_local_fallback,
            attempts=attempts,
        )
        self.record_decision(
            action="coordinator_generate",
            decision=res.get("model_used", self.active_model),
            tools_used=["gemini_api:generateContent"],
            result={"ok": res["ok"], "attempts": attempts, "error": last_err, "fallback_used": res.get("fallback_used", False)},
        )
        return res

    @staticmethod
    def _extract_gemini_text(response_json: dict) -> str:
        cands = response_json.get("candidates") or []
        if not cands:
            return ""
        parts = ((cands[0].get("content") or {}).get("parts")) or []
        texts = [str(p.get("text") or "") for p in parts if isinstance(p, dict) and p.get("text")]
        return "\n".join(texts).strip()

    def _call_local_ollama(self, model_name: str, prompt: str, system_instruction: str, max_output_tokens: int) -> dict:
        full_prompt = f"{system_instruction}\n\n{prompt}".strip() if system_instruction else prompt
        payload = json.dumps(
            {
                "model": model_name,
                "prompt": full_prompt,
                "stream": False,
                "think": False,
                "options": {"num_predict": min(2560, max(128, int(max_output_tokens))), "temperature": 0.2},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            t0 = time.perf_counter()
            with self._http_opener(req, timeout=25.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            text = str(data.get("response") or "").strip()
            return {
                "ok": True,
                "provider": "ollama",
                "model_used": f"ollama/{model_name}",
                "text": text,
                "attempts": 1,
                "elapsed_ms": elapsed_ms,
                "usage": {
                    "prompt_tokens": int(data.get("prompt_eval_count") or 0),
                    "output_tokens": int(data.get("eval_count") or 0),
                    "total_tokens": int(data.get("prompt_eval_count") or 0) + int(data.get("eval_count") or 0),
                },
                "fallback_used": True,
            }
        except Exception as exc:
            return {
                "ok": False,
                "provider": "ollama",
                "model_used": f"ollama/{model_name}",
                "text": "",
                "error": _redact(str(exc)),
                "fallback_used": True,
            }

    def _fallback_response(
        self,
        reason: str,
        prompt: str,
        allow_local_fallback: bool,
        attempts: int = 0,
    ) -> dict:
        local_route = self.router.route("architecture", avoid_vram_swap=True)
        local_model = local_route["selected_model"]
        if not allow_local_fallback:
            return {
                "ok": False,
                "provider": "google",
                "model_used": self.active_model,
                "text": "",
                "attempts": attempts,
                "error": reason,
                "fallback_used": False,
                "recommended_fallback": local_model,
            }
        _, bare_local = _strip_provider_prefix(local_model)
        local_res = self._call_local_ollama(bare_local, prompt, "", 1024)
        local_res["fallback_reason"] = reason
        local_res["fallback_used"] = True
        return local_res

    def record_decision(
        self,
        action: str,
        decision: str,
        tools_used: list[str],
        result: dict,
        project_path: str = "*",
    ) -> dict:
        """Registra de forma auditable decisiones del coordinador, herramientas y resultados."""
        entry = {
            "decision_id": f"gem_{uuid.uuid4().hex[:10]}",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "coordinator_model": self.active_model,
            "project_path": project_path,
            "action": action,
            "decision": _redact(str(decision)),
            "tools_used": list(tools_used),
            "result": json.loads(_redact(json.dumps(result, ensure_ascii=False))),
        }
        try:
            with self._ledger_lock:
                self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.ledger_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                os.chmod(self.ledger_path, 0o600)
        except Exception:
            pass
        return entry

    def get_recent_decisions(self, limit: int = 30) -> list[dict]:
        if not self.ledger_path.is_file():
            return []
        try:
            lines = self.ledger_path.read_text(encoding="utf-8", errors="replace").splitlines()
            return [json.loads(ln) for ln in reversed(lines[-limit:]) if ln.strip()]
        except Exception:
            return []
