---
name: skills-cheatsheet-index
description: Indice dei cheat sheet delle skill e degli agent installati in opencode
---

# Skills — Indice Cheat Sheet

Cheat sheet operative per le skill e gli agent installati in opencode. Niente teoria: solo quando si attivano, cosa fanno e come usarle.

## Come funzionano skill vs agent

| Tipo | Cosa sono | Come si attivano |
|------|-----------|------------------|
| **Skill** | Istruzioni/metodologie che l'agente segue | Automaticamente via tool `skill`, oppure forzandole a parole ("usa la skill X") |
| **Agent** | Subagent specializzati con contesto isolato | Con tool `task`, `subagent_type` = nome dell'agent |

## Skill (per repo di origine)

| Repo | Skill incluse |
|------|---------------|
| [`obra/superpowers/README.md`](obra/superpowers/README.md) — <https://github.com/obra/superpowers> | Metodologia completa idea → design → piano → TDD → review → merge (`brainstorming` · `writing-plans` · `test-driven-development` · `systematic-debugging` · `subagent-driven-development` · ecc.) |
| [`jeffallan/claude-skills/README.md`](jeffallan/claude-skills/README.md) — <https://github.com/jeffallan/claude-skills> | `api-designer` (OpenAPI 3.1) · `fastapi-expert` (FastAPI + Pydantic V2) |
| [`keez97/claude-architecture-skills/README.md`](keez97/claude-architecture-skills/README.md) — <https://github.com/keez97/claude-architecture-skills> | `software-architecture` (Clean Architecture, SOLID, ADR) |
| [`wshobson/agents/README.md`](wshobson/agents/README.md) — <https://github.com/wshobson/agents> | Skill `api-design-principles` **+ 4 agent backend** (`backend-architect` · `performance-engineer` · `security-auditor` · `test-automator`), dal plugin `backend-development` |

### Altre skill (senza repo di origine specificata)
- [`impeccable/README.md`](impeccable/README.md) — design frontend, comandi `audit|polish|bolder|animate|...`
