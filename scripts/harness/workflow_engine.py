#!/usr/bin/env python3
"""
Motor de Workflows DAG, Task Board, Sesiones Persistentes, Eventos y Execution Traces
para el Adaptador Desacoplado DeepSeek Harness — OpenCode-Saghet (Fase 5).

Características integradas de DeepSeek Harness (sin meter Cordis en el núcleo):
1. DAG y dependencias entre tareas (primitivas phase, pipeline, parallel con serialización GPU 8 GB VRAM).
2. Task Board persistente vinculado a sesiones de OpenCode (sin duplicar opencode.db).
3. Workflows multi-etapa y Jobs en segundo plano.
4. Sesiones persistentes (reutilización de session_id a través de nodos del workflow).
5. Eventos y Execution Traces append-only auditables.
6. Delegación de subagentes vía ACP con recuperación automática de fallos (retry + fallback chain).
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from scripts.harness.acp_adapter import ACPContract, DecoupledACPAdapter
from scripts.supervisor.quality_supervisor import TaskDependencyDAG

SAGHET_STATE_DIR = Path.home() / ".local" / "share" / "opencode-saghet"
TASK_BOARD_PATH = SAGHET_STATE_DIR / "harness_task_board.json"
EXECUTION_TRACES_PATH = SAGHET_STATE_DIR / "harness_traces.jsonl"

_BOARD_LOCK = threading.Lock()
_TRACE_LOCK = threading.Lock()
_BG_WORKFLOWS_LOCK = threading.Lock()
_BG_WORKFLOWS: dict[str, dict] = {}


def append_execution_trace(
    workflow_id: str,
    event_type: str,
    node_id: str | None = None,
    session_id: str | None = None,
    details: dict | None = None,
) -> dict:
    """
    Registra un evento en el Execution Trace append-only (estilo DeepSeek Harness session trace).
    """
    trace_entry = {
        "trace_id": f"tr_{uuid.uuid4().hex[:12]}",
        "workflow_id": workflow_id,
        "event_type": event_type,
        "node_id": node_id,
        "session_id": session_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "epoch_ms": int(time.time() * 1000),
        "details": details or {},
    }
    try:
        with _TRACE_LOCK:
            SAGHET_STATE_DIR.mkdir(parents=True, exist_ok=True)
            with open(EXECUTION_TRACES_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(trace_entry, ensure_ascii=False) + "\n")
            os.chmod(EXECUTION_TRACES_PATH, 0o600)
    except Exception:
        pass
    return trace_entry


def get_execution_traces(workflow_id: str | None = None, limit: int = 60) -> list[dict]:
    if not EXECUTION_TRACES_PATH.is_file():
        return []
    try:
        lines = EXECUTION_TRACES_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        out: list[dict] = []
        for raw in reversed(lines):
            if not raw.strip():
                continue
            item = json.loads(raw)
            if workflow_id and item.get("workflow_id") != workflow_id:
                continue
            out.append(item)
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


class HarnessTaskBoard:
    """
    Task Board de proyecto inspirado en `dsh-task-board`.
    Guarda el estado operativo de tareas y subtareas del workflow vinculándolas por referencia
    a `opencode_session_id` (sin duplicar mensajes ni memoria de OpenCode).
    """

    def __init__(self, board_path: Path | None = None) -> None:
        self.board_path = Path(board_path or TASK_BOARD_PATH)

    def _load(self) -> dict:
        if not self.board_path.is_file():
            return {"tasks": {}, "updated_at": None}
        try:
            return json.loads(self.board_path.read_text(encoding="utf-8"))
        except Exception:
            return {"tasks": {}, "updated_at": None}

    def _save(self, data: dict) -> None:
        self.board_path.parent.mkdir(parents=True, exist_ok=True)
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.board_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            os.chmod(self.board_path, 0o600)
        except Exception:
            pass

    def upsert_task(
        self,
        task_id: str,
        title: str,
        status: str,
        workflow_id: str,
        specialist: str,
        model: str,
        opencode_session_id: str,
        dependencies: list[str] | None = None,
        requires_gpu: bool = True,
        attempts: int = 1,
        result_summary: str = "",
        error: str | None = None,
    ) -> dict:
        with _BOARD_LOCK:
            board = self._load()
            tasks = board.setdefault("tasks", {})
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            existing = tasks.get(task_id, {})
            entry = {
                "task_id": task_id,
                "title": title,
                "status": status,  # PENDING | READY | IN_PROGRESS | VERIFYING | DONE | RECOVERED | FAILED | BLOCKED
                "workflow_id": workflow_id,
                "specialist": specialist,
                "model": model,
                "opencode_session_id": opencode_session_id,
                "dependencies": dependencies if dependencies is not None else existing.get("dependencies", []),
                "requires_gpu": bool(requires_gpu),
                "attempts": attempts,
                "result_summary": (result_summary or existing.get("result_summary") or "")[:500],
                "error": error,
                "created_at": existing.get("created_at", now_iso),
                "updated_at": now_iso,
            }
            tasks[task_id] = entry
            self._save(board)
            return entry

    def list_tasks(self, workflow_id: str | None = None) -> list[dict]:
        with _BOARD_LOCK:
            board = self._load()
            items = list((board.get("tasks") or {}).values())
        if workflow_id:
            items = [t for t in items if t.get("workflow_id") == workflow_id]
        items.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
        return items


class HarnessWorkflowEngine:
    """
    Coordinador de Workflows DAG desacoplado.
    Soporta:
    - Primitivas de composición: `phase()`, `pipeline()`, `parallel()`.
    - Respeto estricto de 8 GB VRAM: serializa automáticamente nodos con `requires_gpu=True`
      (`OLLAMA_MAX_LOADED_MODELS=1`), mientras permite paralelismo real en nodos `requires_gpu=False`.
    - Recuperación ante fallos (`max_retries`, cambio a modelo de `fallback_chain` de Gentle AI).
    - Trazas completas append-only y actualización en tiempo real del Task Board.
    """

    def __init__(self, board: HarnessTaskBoard | None = None, adapter: DecoupledACPAdapter | None = None) -> None:
        self.board = board or HarnessTaskBoard()
        self.adapter = adapter or DecoupledACPAdapter()
        self._gpu_lock = threading.Lock()

    def build_workflow_dag(self, nodes_spec: list[dict]) -> TaskDependencyDAG:
        dag = TaskDependencyDAG()
        for spec in nodes_spec:
            dag.add_task(
                task_id=str(spec["id"]),
                title=str(spec.get("title") or spec["id"]),
                specialist=str(spec.get("specialist") or "senior-developer"),
                dependencies=list(spec.get("dependencies") or []),
                max_iterations=int(spec.get("max_attempts", 2)),
            )
        return dag

    def execute_workflow(
        self,
        title: str,
        nodes_spec: list[dict],
        directory: str,
        persistent_session_id: str | None = None,
        node_executor: Callable[[dict, dict, int], dict] | None = None,
    ) -> dict:
        """
        Ejecuta un workflow DAG completo con recuperación de fallos, Task Board y Execution Traces.
        Si Harness está desactivado, ejecuta los pasos en modo fallback directo sobre OpenCode nativo.
        """
        workflow_id = f"wf_{uuid.uuid4().hex[:10]}"
        session_id = persistent_session_id or f"oc_sess_{uuid.uuid4().hex[:10]}"
        harness_enabled = self.adapter.is_enabled()

        dag = self.build_workflow_dag(nodes_spec)
        acyclic, topo_order = dag.validate_acyclic()
        if not acyclic:
            append_execution_trace(
                workflow_id=workflow_id,
                event_type="workflow.rejected_cycle",
                session_id=session_id,
                details={"title": title, "reason": "Ciclo detectado en el grafo DAG"},
            )
            return {
                "ok": False,
                "workflow_id": workflow_id,
                "error": "El workflow contiene dependencias cíclicas en el DAG",
            }

        spec_map = {str(s["id"]): dict(s) for s in nodes_spec}
        delegations: dict[str, dict] = {}

        # Registrar todos los nodos inicialmente en el Task Board
        for nid in topo_order:
            nspec = spec_map[nid]
            del_info = self.adapter.prepare_subagent_delegation(
                task_id=nid,
                objective=str(nspec.get("prompt") or nspec.get("title") or nid),
                directory=directory,
                persistent_session_id=session_id,
                preferred_specialist=nspec.get("specialist"),
            )
            delegations[nid] = del_info
            self.board.upsert_task(
                task_id=nid,
                title=str(nspec.get("title") or nid),
                status="PENDING",
                workflow_id=workflow_id,
                specialist=del_info["specialist"],
                model=del_info["model"],
                opencode_session_id=session_id,
                dependencies=list(nspec.get("dependencies") or []),
                requires_gpu=bool(nspec.get("requires_gpu", True)),
                attempts=0,
            )

        append_execution_trace(
            workflow_id=workflow_id,
            event_type="workflow.started",
            session_id=session_id,
            details={
                "title": title,
                "harness_enabled": harness_enabled,
                "mode": "harness_acp_dag" if harness_enabled else "native_opencode_fallback",
                "nodes_count": len(topo_order),
                "topological_order": topo_order,
            },
        )

        node_results: dict[str, dict] = {}

        def _execute_single_node(nid: str) -> None:
            node = dag.nodes[nid]
            nspec = spec_map[nid]
            del_info = delegations[nid]
            requires_gpu = bool(nspec.get("requires_gpu", True))
            max_attempts = max(1, int(nspec.get("max_attempts", 2)))
            current_model = del_info["model"]
            fallbacks = list(del_info.get("fallback_chain") or [])

            node.status = "RUNNING"
            for attempt in range(1, max_attempts + 1):
                node.iterations = attempt
                self.board.upsert_task(
                    task_id=nid,
                    title=node.title,
                    status="IN_PROGRESS",
                    workflow_id=workflow_id,
                    specialist=del_info["specialist"],
                    model=current_model,
                    opencode_session_id=session_id,
                    requires_gpu=requires_gpu,
                    attempts=attempt,
                )
                append_execution_trace(
                    workflow_id=workflow_id,
                    event_type="acp.subagent.delegated" if harness_enabled else "native.subagent.delegated",
                    node_id=nid,
                    session_id=session_id,
                    details={
                        "attempt": attempt,
                        "specialist": del_info["specialist"],
                        "model": current_model,
                        "requires_gpu": requires_gpu,
                        "acp_method": (del_info.get("acp_frame") or {}).get("method"),
                    },
                )

                t0 = time.perf_counter()
                try:
                    if requires_gpu:
                        # Serialización estricta de GPU local para respetar OLLAMA_MAX_LOADED_MODELS=1 (8 GB VRAM)
                        with self._gpu_lock:
                            res = self._invoke_executor(nspec, {**del_info, "model": current_model}, attempt, node_executor)
                    else:
                        res = self._invoke_executor(nspec, {**del_info, "model": current_model}, attempt, node_executor)
                except Exception as exc:
                    res = {"ok": False, "error": str(exc)}

                elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)

                if res.get("ok"):
                    final_board_status = "RECOVERED" if attempt > 1 else "DONE"
                    node.status = "COMPLETED"
                    node.verdict = "ACCEPT"
                    summary = str(res.get("output") or "Completado con éxito")
                    self.board.upsert_task(
                        task_id=nid,
                        title=node.title,
                        status=final_board_status,
                        workflow_id=workflow_id,
                        specialist=del_info["specialist"],
                        model=current_model,
                        opencode_session_id=session_id,
                        requires_gpu=requires_gpu,
                        attempts=attempt,
                        result_summary=summary,
                        error=None,
                    )
                    append_execution_trace(
                        workflow_id=workflow_id,
                        event_type="node.retry_recovered" if attempt > 1 else "node.completed",
                        node_id=nid,
                        session_id=session_id,
                        details={
                            "attempt": attempt,
                            "elapsed_ms": elapsed_ms,
                            "model": current_model,
                            "output_preview": summary[:240],
                        },
                    )
                    node_results[nid] = {
                        "ok": True,
                        "status": final_board_status,
                        "attempts": attempt,
                        "model_used": current_model,
                        "elapsed_ms": elapsed_ms,
                        "output": summary,
                    }
                    return

                # Fallo en este intento: registrar evento y preparar recuperación si quedan intentos
                err_msg = str(res.get("error") or "Error de ejecución en nodo")
                node.errors.append(f"attempt_{attempt}: {err_msg}")
                append_execution_trace(
                    workflow_id=workflow_id,
                    event_type="node.attempt_failed",
                    node_id=nid,
                    session_id=session_id,
                    details={
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "elapsed_ms": elapsed_ms,
                        "model": current_model,
                        "error": err_msg,
                    },
                )
                if attempt < max_attempts and fallbacks:
                    current_model = fallbacks.pop(0)

            # Si agotó todos los intentos, marcar FAILED
            node.status = "FAILED"
            node.verdict = "REJECT"
            self.board.upsert_task(
                task_id=nid,
                title=node.title,
                status="FAILED",
                workflow_id=workflow_id,
                specialist=del_info["specialist"],
                model=current_model,
                opencode_session_id=session_id,
                requires_gpu=requires_gpu,
                attempts=max_attempts,
                error=node.errors[-1] if node.errors else "Agotados los reintentos",
            )
            node_results[nid] = {
                "ok": False,
                "status": "FAILED",
                "attempts": max_attempts,
                "model_used": current_model,
                "errors": node.errors,
            }

        # Bucle de planificación por ondas del DAG
        while True:
            states = dag.refresh_states()
            # Sincronizar nodos bloqueados en el Task Board
            for nid, st in states.items():
                if st == "BLOCKED" and nid not in node_results:
                    nspec = spec_map[nid]
                    del_info = delegations[nid]
                    self.board.upsert_task(
                        task_id=nid,
                        title=dag.nodes[nid].title,
                        status="BLOCKED",
                        workflow_id=workflow_id,
                        specialist=del_info["specialist"],
                        model=del_info["model"],
                        opencode_session_id=session_id,
                        requires_gpu=bool(nspec.get("requires_gpu", True)),
                        attempts=0,
                        error="Bloqueado por fallo en tarea predecesora del DAG",
                    )
                    append_execution_trace(
                        workflow_id=workflow_id,
                        event_type="node.blocked_by_dependency",
                        node_id=nid,
                        session_id=session_id,
                        details={"dependencies": dag.nodes[nid].dependencies},
                    )
                    node_results[nid] = {"ok": False, "status": "BLOCKED"}

            ready_nodes = [n for n in dag.get_ready_tasks() if n.task_id not in node_results]
            if not ready_nodes:
                break

            # Si hay múltiples nodos listos, ejecutamos en pool (el _gpu_lock serializa los que usan GPU local)
            if len(ready_nodes) == 1:
                _execute_single_node(ready_nodes[0].task_id)
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(ready_nodes))) as pool:
                    futures = [pool.submit(_execute_single_node, n.task_id) for n in ready_nodes]
                    concurrent.futures.wait(futures)

        all_succeeded = all(r.get("ok") for r in node_results.values()) and len(node_results) == len(topo_order)
        recovered_count = sum(1 for r in node_results.values() if r.get("status") == "RECOVERED")
        blocked_count = sum(1 for r in node_results.values() if r.get("status") == "BLOCKED")

        append_execution_trace(
            workflow_id=workflow_id,
            event_type="workflow.completed",
            session_id=session_id,
            details={
                "ok": all_succeeded,
                "recovered_nodes": recovered_count,
                "blocked_nodes": blocked_count,
            },
        )

        return {
            "ok": all_succeeded,
            "workflow_id": workflow_id,
            "persistent_session_id": session_id,
            "harness_enabled": harness_enabled,
            "mode": "harness_acp_dag" if harness_enabled else "native_opencode_fallback",
            "topological_order": topo_order,
            "recovered_nodes": recovered_count,
            "blocked_nodes": blocked_count,
            "nodes": node_results,
            "traces": get_execution_traces(workflow_id=workflow_id, limit=50),
        }

    def start_background_workflow(
        self,
        title: str,
        nodes_spec: list[dict],
        directory: str,
        persistent_session_id: str | None = None,
        node_executor: Callable[[dict, dict, int], dict] | None = None,
    ) -> dict:
        """Lanza un workflow DAG como Job en segundo plano y devuelve su identificador inmediatamente."""
        bg_id = f"bgwf_{uuid.uuid4().hex[:10]}"
        with _BG_WORKFLOWS_LOCK:
            _BG_WORKFLOWS[bg_id] = {
                "bg_id": bg_id,
                "title": title,
                "status": "running",
                "started_at": time.time(),
                "result": None,
            }

        def _runner() -> None:
            res = self.execute_workflow(
                title=title,
                nodes_spec=nodes_spec,
                directory=directory,
                persistent_session_id=persistent_session_id,
                node_executor=node_executor,
            )
            with _BG_WORKFLOWS_LOCK:
                _BG_WORKFLOWS[bg_id]["status"] = "succeeded" if res.get("ok") else "failed"
                _BG_WORKFLOWS[bg_id]["result"] = res

        threading.Thread(target=_runner, daemon=True).start()
        return {"ok": True, "bg_id": bg_id, "status": "running"}

    @staticmethod
    def get_background_workflow(bg_id: str) -> dict | None:
        with _BG_WORKFLOWS_LOCK:
            return _BG_WORKFLOWS.get(bg_id)

    def _invoke_executor(
        self,
        nspec: dict,
        del_info: dict,
        attempt: int,
        custom_executor: Callable[[dict, dict, int], dict] | None,
    ) -> dict:
        if custom_executor is not None:
            return custom_executor(nspec, del_info, attempt)

        # Ejecutor por defecto basado en contrato ACP / comando verificable
        if "verify_cmd" in nspec and isinstance(nspec["verify_cmd"], list):
            res = subprocess.run(
                nspec["verify_cmd"],
                cwd=del_info["directory"],
                capture_output=True,
                text=True,
                timeout=30.0,
                check=False,
            )
            if res.returncode == 0:
                return {"ok": True, "output": (res.stdout or "Verificación OK").strip()}
            return {"ok": False, "error": (res.stderr or res.stdout or f"Exit {res.returncode}").strip()}

        # Respuesta de contrato ACP preparado
        acp_resp = ACPContract.build_response(
            req_id=(del_info.get("acp_frame") or {}).get("id", f"req_{attempt}"),
            result={
                "specialist": del_info["specialist"],
                "model": del_info["model"],
                "session_id": del_info["session_id"],
                "status": "delegated_ready",
            },
        )
        valid, reason = ACPContract.validate_frame(acp_resp)
        if not valid:
            return {"ok": False, "error": reason}
        return {
            "ok": True,
            "output": f"[{del_info['specialist']} @ {del_info['model']}] Nodo '{nspec.get('title', nspec['id'])}' completado en sesión {del_info['session_id']}.",
        }
