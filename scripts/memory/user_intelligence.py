#!/usr/bin/env python3
"""
User Intelligence Engine — OpenCode-Saghet Cognitive V2 (Fase 1).

Construye y mantiene un modelo contextual, local-first y auditable del usuario sobre
`HierarchicalMemoryStore` (sin crear bases de datos redundantes):
- Preferencias explícitas vs. inferidas, y temporales vs. permanentes.
- Resolución de conflictos y vigencia (explicit > inferred; reciente > obsoleto).
- Aprendizaje mediante correcciones y señales de aceptación/rechazo.
- Privacidad estricta (cero secretos, bloqueo de preferencias sensibles sin autorización,
  inspección, corrección y borrado).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from scripts.memory.hierarchical_memory import (
    HierarchicalMemoryStore,
    contains_sensitive_secret,
)

_SENSITIVE_TOPIC_RE = re.compile(
    r"\b(religi[oó]n|religion|pol[ií]tica|political|salud|health|m[eé]dic[oa]|medical|"
    r"orientaci[oó]n\s+sexual|sexual\s+orientation|bancari[oa]|bank\s+account|tarjeta|credit\s+card|"
    r"salario|salary|biom[eé]tric[oa]|biometric|dni|pasaporte|passport|ssn)\b",
    re.IGNORECASE,
)

# Patrones multilingües (ES/EN) para detectar correcciones del usuario
_CORRECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "duplicate_functionality",
        re.compile(
            r"\b(ya\s+tengo\s+esa\s+funcionalidad|ya\s+existe|no\s+vuelvas\s+a\s+implementar|"
            r"already\s+have\s+that|already\s+exists|don'?t\s+reimplement)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "over_engineered",
        re.compile(
            r"\b(demasiado\s+complej[oa]|muy\s+complej[oa]|sobreingenier[ií]a|innecesariamente\s+complej[oa]|"
            r"too\s+complex|over[- ]?engineered|overkill|keep\s+it\s+simple)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "wrong_architecture",
        re.compile(
            r"\b(no\s+quiero\s+esa\s+arquitectura|esa\s+arquitectura\s+no|"
            r"don'?t\s+want\s+that\s+architecture|wrong\s+architecture)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "misunderstood_intent",
        re.compile(
            r"\b(eso\s+no\s+era\s+lo\s+que\s+ped[ií]|no\s+es\s+lo\s+que\s+ped[ií]|me\s+entendiste\s+mal|"
            r"that'?s\s+not\s+what\s+i\s+asked|not\s+what\s+i\s+meant|misunderstood)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "style_mismatch",
        re.compile(
            r"\b(prefiero\s+hacerlo\s+de\s+otra\s+manera|hazlo\s+de\s+otra\s+forma|"
            r"prefer\s+to\s+do\s+it\s+differently|wrong\s+approach)\b",
            re.IGNORECASE,
        ),
    ),
)

# Patrones ligeros para capturar preferencias explícitas desde mensajes naturales
_EXPLICIT_PREF_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "architecture.simplicity",
        "Priorizar simplicidad, eficiencia y evitar complejidad innecesaria.",
        re.compile(
            r"\b(prioriza\s+simplicidad|soluciones?\s+simples?\s+y\s+eficientes?|sin\s+complejidad\s+innecesaria|"
            r"prefer\s+simplicity|keep\s+it\s+simple|avoid\s+unnecessary\s+complexity)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "communication.language",
        "Responder en español manteniendo terminología técnica precisa.",
        re.compile(r"\b(resp[oó]ndeme\s+en\s+espa[nñ]ol|habla\s+en\s+espa[nñ]ol|respond\s+in\s+spanish)\b", re.IGNORECASE),
    ),
    (
        "communication.language",
        "Respond in English with precise technical terminology.",
        re.compile(r"\b(respond\s+in\s+english|answer\s+in\s+english|responde\s+en\s+ingl[eé]s)\b", re.IGNORECASE),
    ),
    (
        "communication.conciseness",
        "Respuestas concisas, directas y basadas en evidencia verificable.",
        re.compile(r"\b(s[eé]\s+conciso|respuestas?\s+cortas?|sin\s+rodeos|be\s+concise|keep\s+responses?\s+brief)\b", re.IGNORECASE),
    ),
    (
        "autonomy.level",
        "Ejecutar con alta autonomía cuando la intención es clara y preguntar solo ante cambios críticos/irreversibles.",
        re.compile(r"\b(no\s+preguntes\s+por\s+todo|act[uú]a\s+con\s+autonom[ií]a|don'?t\s+ask\s+for\s+everything)\b", re.IGNORECASE),
    ),
)


class UserIntelligenceEngine:
    """
    Motor de Inteligencia de Usuario sobre `HierarchicalMemoryStore`.
    Gestiona preferencias (explícitas/inferidas, temporales/permanentes),
    resolución de conflictos, aprendizaje por correcciones y privacidad.
    """

    def __init__(self, memory_store: HierarchicalMemoryStore | None = None) -> None:
        self.memory = memory_store or HierarchicalMemoryStore()

    @staticmethod
    def is_sensitive_preference(preference_key: str, content: str) -> bool:
        return bool(_SENSITIVE_TOPIC_RE.search(f"{preference_key} {content}"))

    def record_preference(
        self,
        preference_key: str,
        value_description: str,
        source: str = "explicit",
        scope: str = "permanent",
        project_path: str = "*",
        session_id: str = "",
        provenance: str | None = None,
        valid_until: str | None = None,
        importance: float | None = None,
        evidence: dict | None = None,
        sensitive_authorized: bool = False,
        tags: list[str] | None = None,
    ) -> dict:
        """
        Registra o actualiza una preferencia del usuario aplicando reglas estrictas:
        - `explicit` tiene prioridad sobre `inferred`.
        - Una observación `inferred` aislada se guarda como `provisional` hasta repetirse (>= 2).
        - Resuelve conflictos por `preference_key` marcando recuerdos previos como `superseded`.
        """
        clean_key = (preference_key or "").strip().lower()
        clean_val = (value_description or "").strip()
        norm_source = "explicit" if source == "explicit" else "inferred"
        norm_scope = "temporary" if scope == "temporary" else "permanent"

        if not clean_key or not clean_val:
            return {"ok": False, "error": "preference_key y value_description son obligatorios"}
        if contains_sensitive_secret(clean_key) or contains_sensitive_secret(clean_val):
            return {"ok": False, "error": "Bloqueado por privacidad: contiene secretos o credenciales"}
        if norm_scope == "permanent" and self.is_sensitive_preference(clean_key, clean_val) and not sensitive_authorized:
            return {
                "ok": False,
                "error": "Bloqueado por privacidad: preferencia permanente sensible requiere autorización explícita",
            }

        norm_proj = str(Path(project_path).resolve()) if project_path and project_path != "*" else "*"
        # Buscar preferencias activas con la misma clave en el mismo ámbito de proyecto (o global si coincide)
        existing_active = self.memory.inspect_memories(
            tier="user",
            category="user_preference",
            project_path=norm_proj,
            preference_key=clean_key,
            limit=20,
        )
        active_same_key = [m for m in existing_active if m.get("status") in {"valid", "provisional"}]

        # Verificar conflictos antes de almacenar
        to_supersede: list[dict] = []
        for old in active_same_key:
            old_content = (old.get("content") or "").strip()
            if old_content.lower() == clean_val.lower():
                continue  # Es la misma preferencia; store_memory la deduplicará/reforzará
            old_source = old.get("preference_source") or "inferred"
            # Regla de prioridad: explicit > inferred
            if norm_source == "inferred" and old_source == "explicit":
                return {
                    "ok": True,
                    "ignored_inferred": True,
                    "reason": "Existe una preferencia explícita vigente que tiene prioridad sobre inferencias.",
                    "active_preference_id": old["id"],
                }
            # Si la nueva es explícita, o ambas son inferidas contradictorias, la nueva reemplaza a la anterior
            to_supersede.append(old)

        # Una preferencia inferida aislada inicia como provisional; solo se promueve tras >= 2 observaciones
        initial_status = "valid" if norm_source == "explicit" else "provisional"
        conf = 0.96 if norm_source == "explicit" else 0.62
        imp = importance if importance is not None else (0.9 if norm_scope == "permanent" and norm_source == "explicit" else 0.65)
        prov = provenance or f"user:{norm_source}"

        merged_tags = sorted({"user_preference", norm_source, norm_scope, clean_key, *(tags or [])})
        res = self.memory.store_memory(
            tier="user",
            category="user_preference",
            title=f"Preferencia ({clean_key})",
            content=clean_val,
            provenance=prov,
            project_path=norm_proj,
            session_id=session_id,
            context={
                "tags": merged_tags,
                "preference_key": clean_key,
                "preference_source": norm_source,
                "preference_scope": norm_scope,
            },
            confidence=conf,
            similarity_threshold=0.90,
            status=initial_status,
            valid_until=valid_until,
            importance=imp,
            preference_source=norm_source,
            preference_scope=norm_scope,
            preference_key=clean_key,
            evidence=evidence or {"source": norm_source, "scope": norm_scope},
        )

        if not res.get("ok"):
            return res

        superseded_ids: list[str] = []
        for old in to_supersede:
            if old["id"] != res["id"]:
                inv = self.memory.invalidate_memory(
                    old["id"],
                    reason=f"Reemplazada por preferencia {norm_source} más reciente ({clean_key})",
                    new_status="superseded",
                    superseded_by=res["id"],
                )
                if inv.get("ok"):
                    superseded_ids.append(old["id"])

        res["preference_key"] = clean_key
        res["preference_source"] = norm_source
        res["preference_scope"] = norm_scope
        res["superseded_ids"] = superseded_ids
        return res

    def record_correction(
        self,
        user_message: str,
        failed_interpretation: str = "",
        correct_expectation: str = "",
        project_path: str = "*",
        session_id: str = "",
        correction_type: str | None = None,
    ) -> dict:
        """
        Registra una corrección explícita del usuario para evitar repetir el mismo error
        y actualiza preferencias relacionadas cuando corresponda.
        """
        clean_msg = (user_message or "").strip()
        if not clean_msg:
            return {"ok": False, "error": "El mensaje de corrección no puede estar vacío"}
        if contains_sensitive_secret(clean_msg):
            return {"ok": False, "error": "Bloqueado por privacidad: el mensaje contiene secretos"}

        detected_type = correction_type or self.classify_correction_type(clean_msg)
        summary_parts = [f"Tipo: {detected_type}", f"Corrección usuario: {clean_msg}"]
        if failed_interpretation:
            summary_parts.append(f"Interpretación/decisión fallida: {failed_interpretation.strip()}")
        if correct_expectation:
            summary_parts.append(f"Expectativa correcta: {correct_expectation.strip()}")

        res = self.memory.store_memory(
            tier="experience",
            category="user_correction",
            title=f"Corrección de usuario ({detected_type})",
            content="\n".join(summary_parts),
            provenance="user:correction",
            project_path=project_path,
            session_id=session_id,
            context={
                "tags": ["user_correction", detected_type],
                "correction_type": detected_type,
                "failed_interpretation": failed_interpretation,
                "correct_expectation": correct_expectation,
            },
            confidence=0.95,
            status="valid",
            importance=0.90,
            evidence={"user_message": clean_msg, "detected_type": detected_type},
        )

        # Actualizar modelo de preferencias cuando la corrección implica un criterio claro
        if detected_type == "over_engineered":
            self.record_preference(
                preference_key="architecture.simplicity",
                value_description="Priorizar simplicidad, eficiencia y evitar soluciones sobre-diseñadas.",
                source="explicit",
                scope="permanent",
                project_path=project_path,
                session_id=session_id,
                provenance="user:correction",
                evidence={"trigger_correction_id": res.get("id")},
            )
        elif detected_type == "duplicate_functionality":
            self.record_preference(
                preference_key="workflow.reuse_existing",
                value_description="Inspeccionar capacidades existentes antes de proponer o implementar nuevos módulos.",
                source="explicit",
                scope="permanent",
                project_path=project_path,
                session_id=session_id,
                provenance="user:correction",
                evidence={"trigger_correction_id": res.get("id")},
            )

        res["correction_type"] = detected_type
        return res

    @staticmethod
    def classify_correction_types(message: str) -> list[str]:
        text = (message or "").strip()
        return [ctype for ctype, pattern in _CORRECTION_PATTERNS if pattern.search(text)]

    @classmethod
    def classify_correction_type(cls, message: str) -> str:
        matches = cls.classify_correction_types(message)
        return matches[0] if matches else "other"

    def record_outcome_signal(
        self,
        solution_summary: str,
        accepted: bool,
        reason: str = "",
        project_path: str = "*",
        session_id: str = "",
        tags: list[str] | None = None,
    ) -> dict:
        """Registra soluciones aceptadas o rechazadas y el motivo del rechazo."""
        clean_sol = (solution_summary or "").strip()
        if not clean_sol:
            return {"ok": False, "error": "solution_summary no puede estar vacío"}
        category = "accepted_solution" if accepted else "rejected_solution"
        title = f"Solución {'aceptada' if accepted else 'rechazada'}: {clean_sol[:90]}"
        content = clean_sol if not reason else f"{clean_sol}\nMotivo: {reason.strip()}"
        return self.memory.store_memory(
            tier="user",
            category=category,
            title=title,
            content=content,
            provenance="user:outcome_feedback",
            project_path=project_path,
            session_id=session_id,
            context={"tags": [category, *(tags or [])], "accepted": accepted, "reason": reason},
            confidence=0.92 if not accepted else 0.85,
            status="valid",
            importance=0.85 if not accepted else 0.70,
            evidence={"accepted": accepted, "reason": reason},
        )

    def detect_and_capture_from_message(
        self,
        message: str,
        project_path: str = "*",
        session_id: str = "",
    ) -> dict:
        """
        Analiza un mensaje natural del usuario (ES/EN) para capturar automáticamente
        correcciones o preferencias explícitas sin almacenar secretos ni ruido.
        """
        text = (message or "").strip()
        if not text or contains_sensitive_secret(text):
            return {"captured": False, "preferences": [], "correction": None}

        captured_prefs: list[dict] = []
        for pref_key, pref_desc, pat in _EXPLICIT_PREF_RULES:
            if pat.search(text):
                res = self.record_preference(
                    preference_key=pref_key,
                    value_description=pref_desc,
                    source="explicit",
                    scope="permanent",
                    project_path=project_path,
                    session_id=session_id,
                    provenance="user:message_explicit",
                )
                if res.get("ok"):
                    captured_prefs.append(res)

        correction_res = None
        ctypes = self.classify_correction_types(text)
        if ctypes:
            correction_res = self.record_correction(
                user_message=text,
                project_path=project_path,
                session_id=session_id,
                correction_type=ctypes[0],
            )
            # Aplicar también preferencias derivadas de señales secundarias en el mismo mensaje
            for extra_type in ctypes[1:]:
                if extra_type == "over_engineered":
                    self.record_preference(
                        preference_key="architecture.simplicity",
                        value_description="Priorizar simplicidad, eficiencia y evitar soluciones sobre-diseñadas.",
                        source="explicit",
                        scope="permanent",
                        project_path=project_path,
                        session_id=session_id,
                        provenance="user:correction",
                    )
                elif extra_type == "duplicate_functionality":
                    self.record_preference(
                        preference_key="workflow.reuse_existing",
                        value_description="Inspeccionar capacidades existentes antes de proponer o implementar nuevos módulos.",
                        source="explicit",
                        scope="permanent",
                        project_path=project_path,
                        session_id=session_id,
                        provenance="user:correction",
                    )

        return {
            "captured": bool(captured_prefs or correction_res),
            "preferences": captured_prefs,
            "correction": correction_res,
        }

    def get_user_profile(
        self,
        project_path: str = "*",
        query: str = "",
        limit_preferences: int = 8,
        limit_corrections: int = 4,
    ) -> dict:
        """
        Construye un perfil contextual compacto y vigente del usuario (sin recuerdos superseded/invalidados).
        """
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        norm_proj = str(Path(project_path).resolve()) if project_path and project_path != "*" else "*"

        all_prefs = self.memory.inspect_memories(tier="user", category="user_preference", limit=80)
        active_prefs: list[dict] = []
        for p in all_prefs:
            if p.get("status") != "valid":
                continue
            if p.get("valid_until") and p["valid_until"] < now_iso:
                continue
            p_proj = p.get("project_path", "*")
            if norm_proj != "*" and p_proj not in {"*", norm_proj}:
                continue
            active_prefs.append(p)

        # Deduplicar por preference_key priorizando explícitas y específicas de proyecto
        by_key: dict[str, dict] = {}
        for p in active_prefs:
            k = p.get("preference_key") or p["id"]
            prev = by_key.get(k)
            if prev is None:
                by_key[k] = p
                continue
            p_rank = (1 if p.get("preference_source") == "explicit" else 0, 1 if p.get("project_path") == norm_proj else 0)
            prev_rank = (1 if prev.get("preference_source") == "explicit" else 0, 1 if prev.get("project_path") == norm_proj else 0)
            if p_rank > prev_rank:
                by_key[k] = p

        selected_prefs = list(by_key.values())[:limit_preferences]

        # Correcciones y soluciones rechazadas recientes
        corrections = [
            c
            for c in self.memory.inspect_memories(tier="experience", category="user_correction", limit=20)
            if c.get("status") == "valid" and (norm_proj == "*" or c.get("project_path") in {"*", norm_proj})
        ][:limit_corrections]

        rejected = [
            r
            for r in self.memory.inspect_memories(tier="user", category="rejected_solution", limit=15)
            if r.get("status") == "valid" and (norm_proj == "*" or r.get("project_path") in {"*", norm_proj})
        ][:4]

        relevant_contextual = []
        if query:
            relevant_contextual = self.memory.retrieve_relevant_memories(
                query=query,
                project_path=norm_proj,
                tiers=["user", "project", "experience"],
                include_provisional=False,
                limit=5,
            )

        language_pref = "es"
        for p in selected_prefs:
            if p.get("preference_key") == "communication.language" and "english" in p.get("content", "").lower():
                language_pref = "en"
                break

        return {
            "project_path": norm_proj,
            "preferred_language": language_pref,
            "active_preferences": [
                {
                    "id": p["id"],
                    "key": p.get("preference_key"),
                    "content": p["content"],
                    "source": p.get("preference_source"),
                    "scope": p.get("preference_scope"),
                    "confidence": p["confidence"],
                }
                for p in selected_prefs
            ],
            "recent_corrections": [
                {"id": c["id"], "title": c["title"], "content": c["content"]}
                for c in corrections
            ],
            "rejected_solutions": [
                {"id": r["id"], "title": r["title"], "content": r["content"]}
                for r in rejected
            ],
            "relevant_memories": relevant_contextual,
        }

    def inspect_user_model(self, include_superseded: bool = False) -> list[dict]:
        """Inspección transparente del modelo de usuario (privacidad y auditabilidad)."""
        statuses = None if include_superseded else "valid"
        prefs = self.memory.inspect_memories(tier="user", status=statuses, limit=100)
        corrs = self.memory.inspect_memories(tier="experience", category="user_correction", status=statuses, limit=50)
        return prefs + corrs

    def correct_user_memory(self, memory_id: str, new_content: str) -> dict:
        return self.memory.correct_memory(memory_id=memory_id, new_content=new_content, provenance="user:manual_edit")

    def delete_user_memory(self, memory_id: str) -> dict:
        return self.memory.delete_memory(memory_id=memory_id)
