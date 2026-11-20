---
description: Rebuild the OpenCode skill registry for the current project and installed skills via Gentle AI
agent: saghet-orchestrator
subtask: true
---

Load `skill-registry` first, then rebuild the skill registry for the current project and configured skill directories using `gentle-ai skill-registry refresh --cwd .`.

Return the registry path, skill count, cache status, and verification output.
