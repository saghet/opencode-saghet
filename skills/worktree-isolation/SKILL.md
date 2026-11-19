---
name: worktree-isolation
description: Aislamiento de ramas mediante git worktree para cambios experimentales o refactorizaciones sin corromper el árbol principal.
---

# Aislamiento con Git Worktree

1. **Crear worktree aislado:**
   ```bash
   git worktree add ../wt-<nombre> -b feat/<nombre>
   ```
2. **Trabajar y validar dentro de `../wt-<nombre>`** sin mutar el árbol principal.
3. **Revisar diferencias antes de integrar:**
   ```bash
   git -C ../wt-<nombre> diff main
   ```
4. **Integrar o descartar y limpiar:**
   ```bash
   git merge --no-ff feat/<nombre>
   git worktree remove ../wt-<nombre>
   ```
