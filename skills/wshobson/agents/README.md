---
name: wshobson-agents
repo: https://github.com/wshobson/agents
source: https://github.com/wshobson/agents/tree/main/plugins/backend-development
---

# wshobson/agents — Cheat Sheet

Repo ufficiale: <https://github.com/wshobson/agents>

Da questa repo sono installati 1 skill e 4 agent, tutti dal plugin `backend-development` (`plugins/backend-development/`).

## Skill

- [`api-design-principles/README.md`](api-design-principles/README.md) — principi REST/GraphQL, versioning, pagination, best practice

## Agent backend

Dalla cartella `plugins/backend-development/agents/`. Si invocano con il tool `task`, `subagent_type` = nome dell'agent. Vanno usati PROATTIVAMENTE durante lo sviluppo feature.

| Agent (subagent_type) | Quando | Cosa fa |
|------------------------|--------|---------|
| `backend-development-backend-architect` | Nuovi servizi/API, architettura backend | REST/GraphQL/gRPC/WebSocket, confini di servizio, resilience, observability |
| `backend-development-performance-engineer` | Review performance di feature | Profiling, DB (N+1, indici), caching, concorrenza, load testing, scalabilità |
| `backend-development-security-auditor` | Review sicurezza di feature | OWASP Top 10, auth/authz, injection, data protection, API security, dipendenze CVE |
| `backend-development-test-automator` | Creazione test suite | Unit/integration/E2E, TDD/BDD, fixtures, mocking, coverage analysis |

### Esempi di invocazione

```
"Fai una review di sicurezza del nuovo endpoint POST /trips"
→ task, subagent_type: backend-development-security-auditor

"Profilare la pipeline di ricerca SerpAPI, trovare i colli di bottiglia"
→ task, subagent_type: backend-development-performance-engineer

"Scrivi i test per src/pipeline.py"
→ task, subagent_type: backend-development-test-automator

"Riprogetta l'architettura del servizio email"
→ task, subagent_type: backend-development-backend-architect
```

### Cosa restituiscono

- **backend-architect**: design con boundary chiari, contract ben definiti, resilience fin dall'inizio
- **performance-engineer**: 1) Profile → hot spot · 2) Measure impatto (response time, memoria, throughput) · 3) Classify Critical (>500ms) / High (100-500ms) / Medium (50-100ms) / Low (<50ms) · 4) Recommend con esempi before/after
- **security-auditor**: 1) Scan · 2) Classify per severità · 3) Explain con attack vector e impatto · 4) Recommend fix con codice · 5) Validate auth/authz/input validation
- **test-automator**: 1) Detect framework test del progetto · 2) Analyze codice · 3) Design test (happy path, edge case, errori, boundary) · 4) Write seguendo le convenzioni · 5) Verify eseguibilità

### Note d'uso

- Gli agent hanno **contesto isolato**: fornisci nel prompt percorsi file, errori e requisiti — non ereditano la tua sessione.
- In combinazione con superpowers: si abbinano bene a `subagent-driven-development` (implementer/reviewer specializzati) e a `dispatching-parallel-agents` (2+ review indipendenti in parallelo).
- La repo contiene altri agent non installati: `event-sourcing-architect`, `graphql-architect`, `tdd-orchestrator`, `temporal-python-pro`.
