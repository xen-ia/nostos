---
name: claude-architecture-skills
repo: https://github.com/keez97/claude-architecture-skills
source: https://github.com/keez97/claude-architecture-skills/tree/main/skills
---

# keez97/claude-architecture-skills — Cheat Sheet

Repo ufficiale: <https://github.com/keez97/claude-architecture-skills>

## Skill di questa repo

- [`software-architecture/README.md`](software-architecture/README.md) — design di sistema, Clean Architecture, SOLID, ADR, audit

## Cosa altro contiene la repo (non installato qui)

7 skill totali. Quella installata è `software-architecture`; le altre utili:

| Skill | Cosa fa |
|-------|---------|
| `architecture-workflow` | Orchestratore 4 fasi: Discover → Diagnose → Fix (checkpoint utente) → Document |
| `python-architecture-review` | Analisi backend Python (FastAPI, SQLAlchemy, async) |
| `microservices-architect` | Confini di servizio, saga patterns, monolith vs microservices |
| `cloud-infrastructure` | AWS: Terraform/CDK, costi, sicurezza |
| `modern-web-app-architecture` | Frontend: rendering, state, bundle, Core Web Vitals |
| `describe-design` | Reverse-engineering del codice in documenti C4/sequence/ER |

## Note

- Le skill sono file `.skill` (zip) in `skills/`; installazione ufficiale prevista per Claude Code (Settings > Skills > Install from file).
- Benchmark A/B interni nel repo (`benchmarks/`), valutati dall'autore stesso — da leggere come segnale di sviluppo, non come validazione indipendente.
- MIT license.