#!/usr/bin/env python3
"""Gestor programático de aislamiento mediante Git Worktree con validación y rollback."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

SAGHET_STATE_DIR = Path.home() / ".local" / "share" / "opencode-saghet"
WORKTREES_ROOT = SAGHET_STATE_DIR / "worktrees"


def _run_git(repo_dir: Path, args: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def is_git_repo(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    res = _run_git(directory, ["rev-parse", "--is-inside-work-tree"], timeout=3.0)
    return res.returncode == 0 and res.stdout.strip() == "true"


def create_worktree(repo_dir: Path, task_id: str, base_ref: str = "HEAD") -> dict:
    """Crea un git worktree aislado para una tarea de implementación o refactorización."""
    repo_dir = repo_dir.resolve()
    if not is_git_repo(repo_dir):
        return {"ok": False, "error": f"No es un repositorio Git: {repo_dir}"}

    safe_id = "".join(c for c in task_id if c.isalnum() or c in "-_")[:32] or f"task-{int(time.time())}"
    WORKTREES_ROOT.mkdir(parents=True, exist_ok=True)
    wt_path = WORKTREES_ROOT / f"{repo_dir.name}-{safe_id}"
    branch_name = f"saghet/wt-{safe_id}"

    if wt_path.exists():
        _run_git(repo_dir, ["worktree", "remove", "--force", str(wt_path)])
        if wt_path.exists():
            shutil.rmtree(wt_path, ignore_errors=True)
    _run_git(repo_dir, ["branch", "-D", branch_name])

    res = _run_git(repo_dir, ["worktree", "add", str(wt_path), "-b", branch_name, base_ref])
    if res.returncode != 0:
        return {"ok": False, "error": (res.stderr or res.stdout).strip()}

    return {
        "ok": True,
        "repo_dir": str(repo_dir),
        "worktree_path": str(wt_path),
        "branch": branch_name,
        "task_id": safe_id,
        "created_at": int(time.time() * 1000),
    }


def inspect_worktree(wt_path: Path) -> dict:
    """Inspecciona el estado real de un worktree: archivos modificados, diff y limpieza."""
    wt_path = wt_path.resolve()
    if not is_git_repo(wt_path):
        return {"ok": False, "error": f"Worktree inválido: {wt_path}"}

    status_res = _run_git(wt_path, ["status", "--porcelain"])
    diff_res = _run_git(wt_path, ["diff", "HEAD"])
    stat_res = _run_git(wt_path, ["diff", "--stat", "HEAD"])

    changed_files = []
    for line in status_res.stdout.splitlines():
        if line.strip():
            changed_files.append(line[3:].strip())

    return {
        "ok": True,
        "worktree_path": str(wt_path),
        "has_changes": bool(changed_files or diff_res.stdout.strip()),
        "changed_files": changed_files,
        "diff_stat": stat_res.stdout.strip(),
        "diff_bytes": len(diff_res.stdout.encode("utf-8")),
        "diff_preview": diff_res.stdout[:4000],
    }


def run_verification_in_worktree(wt_path: Path, command: list[str], timeout: float = 60.0) -> dict:
    """Ejecuta pruebas o validaciones reales dentro del worktree aislado."""
    wt_path = wt_path.resolve()
    if not wt_path.is_dir():
        return {"ok": False, "returncode": -1, "output": f"No existe worktree: {wt_path}"}

    t0 = time.perf_counter()
    try:
        res = subprocess.run(
            command,
            cwd=str(wt_path),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "ok": res.returncode == 0,
            "returncode": res.returncode,
            "elapsed_ms": elapsed_ms,
            "command": command,
            "output": (res.stdout + "\n" + res.stderr).strip()[:8000],
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "ok": False,
            "returncode": -1,
            "elapsed_ms": elapsed_ms,
            "command": command,
            "output": f"Error ejecutando verificación: {exc}",
        }


def rollback_worktree(repo_dir: Path, wt_path: Path, branch_name: str | None = None) -> dict:
    """Descarta y limpia de forma segura un worktree cuya validación falló."""
    repo_dir = repo_dir.resolve()
    wt_path = wt_path.resolve()
    _run_git(repo_dir, ["worktree", "remove", "--force", str(wt_path)])
    if wt_path.exists():
        shutil.rmtree(wt_path, ignore_errors=True)
    if branch_name:
        _run_git(repo_dir, ["branch", "-D", branch_name])
    return {
        "ok": not wt_path.exists(),
        "rolled_back_worktree": str(wt_path),
        "deleted_branch": branch_name,
    }


def merge_worktree(repo_dir: Path, wt_path: Path, branch_name: str, commit_message: str) -> dict:
    """Comitea cambios pendientes en el worktree, los fusiona en el repositorio base y limpia el worktree."""
    repo_dir = repo_dir.resolve()
    wt_path = wt_path.resolve()
    if not is_git_repo(wt_path):
        return {"ok": False, "error": f"Worktree no válido: {wt_path}"}

    status = _run_git(wt_path, ["status", "--porcelain"])
    if status.stdout.strip():
        _run_git(wt_path, ["add", "-A"])
        commit_res = _run_git(wt_path, ["commit", "-m", commit_message])
        if commit_res.returncode != 0:
            return {"ok": False, "error": (commit_res.stderr or commit_res.stdout).strip()}

    merge_res = _run_git(repo_dir, ["merge", "--no-ff", branch_name, "-m", f"Merge {branch_name}: {commit_message}"])
    if merge_res.returncode != 0:
        _run_git(repo_dir, ["merge", "--abort"])
        return {"ok": False, "error": (merge_res.stderr or merge_res.stdout).strip()}

    rollback_worktree(repo_dir, wt_path, branch_name)
    return {
        "ok": True,
        "merged_branch": branch_name,
        "output": merge_res.stdout.strip(),
    }


def list_worktrees(repo_dir: Path) -> list[dict]:
    repo_dir = repo_dir.resolve()
    if not is_git_repo(repo_dir):
        return []
    res = _run_git(repo_dir, ["worktree", "list", "--porcelain"])
    if res.returncode != 0:
        return []
    items: list[dict] = []
    current: dict = {}
    for line in res.stdout.splitlines():
        if not line.strip():
            if current:
                items.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line[len("worktree ") :].strip()
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD ") :].strip()
        elif line.startswith("branch "):
            current["branch"] = line[len("branch ") :].strip()
    if current:
        items.append(current)
    return items
