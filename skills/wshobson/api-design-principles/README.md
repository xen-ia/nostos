---
name: api-design-principles
source: https://github.com/wshobson/agents/blob/main/plugins/backend-development/skills/api-design-principles/SKILL.md
repo: https://github.com/wshobson/agents
---

# API Design Principles — Cheat Sheet

Skill globale: `backend-development-api-design-principles`

## Quando si attiva

- Progettare nuove REST/GraphQL API
- Refactoring di API esistenti per migliorarne l'usabilità
- Definire standard API di team
- Review di specifiche prima dell'implementazione

## Principi REST

- **Risorse = nomi** (`/users`), azioni = metodi HTTP (GET/POST/PUT/PATCH/DELETE)
- GET = retrieve (idempotente) · POST = create · PUT = replace (idempotente) · PATCH = update parziale · DELETE = remove
- URL gerarchici, naming coerente, plurali per collezioni (`/users`, non `/user`)
- **Stateless**: ogni richiesta autosufficiente

## Principi GraphQL

- **Schema-first**: progetta lo schema prima dei resolver
- Queries = lettura · Mutations = modifica · Subscriptions = realtime
- Un solo endpoint, clienti chiedono esattamente ciò che serve
- **Evita N+1** con DataLoaders
- Errori strutturati nei payload delle mutation
- Deprecazioni con `@deprecated` (migrazione graduale)
- Monitora query complexity e tempi

## Versioning

| Strategia | Esempio |
|-----------|---------|
| URL | `/api/v1/users` |
| Header | `Accept: application/vnd.api+json; version=1` |
| Query param | `/api/users?version=1` |

Pianifica breaking changes dal primo giorno.

## Best practice

1. Pagination su tutte le collezioni grandi (cursor-based per GraphQL, Relay spec)
2. Rate limiting su ogni API
3. Status code corretti (2xx/4xx/5xx)
4. Errori con formato standardizzato (mai inconsistente)
5. Documentazione OpenAPI/Swagger interattiva
6. Coerenza dei nomi ovunque (stessa convenzione, nessuna eccezione)

## Pitfall comuni (da evitare)

- POST per operazioni idempotenti
- Breaking changes senza versioning
- Formati di errore incoerenti
- API senza rate limit
- Over/under-fetching
- Documentazione assente

## Comandi operativi

- Dettagli e pattern approfonditi: `references/details.md`
- Spec OpenAPI per contract: usa la skill `api-designer`
