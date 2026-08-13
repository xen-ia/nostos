---
name: api-designer
source: https://github.com/Jeffallan/claude-skills/blob/main/skills/api-designer/SKILL.md
repo: https://github.com/Jeffallan/claude-skills
---

# API Designer — Cheat Sheet

Skill globale: `api-designer`

## Quando si attiva

- Progettare REST/GraphQL API e relative specifiche OpenAPI
- Creare specifiche OpenAPI 3.1
- Pianificare architettura API, versioning, pagination, error handling

## Core Workflow

1. **Analyze domain** — requisiti di business, modelli dati, esigenze client
2. **Model resources** — identifica risorse/relazioni/operazioni; schizza il diagramma entità PRIMA della spec
3. **Design endpoints** — URI, metodi HTTP, schemi request/response
4. **Specify contract** — crea OpenAPI 3.1 e valida:
   ```bash
   npx @redocly/cli lint openapi.yaml
   ```
5. **Mock and verify** — mock server per testare i contract:
   ```bash
   npx @stoplight/prism-cli mock openapi.yaml
   ```
6. **Plan evolution** — versioning, deprecation, backward-compatibility

## MUST DO

- REST resource-oriented, HTTP method corretti
- Una sola convenzione di naming (snake_case o camelCase) ovunque
- OpenAPI 3.1 completo
- Errori RFC 7807 con messaggi azionabili
- Pagination su tutte le collezioni
- Versioning con policy di deprecation chiare
- Auth documentata + esempi request/response

## MUST NOT DO

- Verbi nelle URI (`/users/{id}` sì, `/getUser/{id}` no)
- Strutture di risposta inconsistenti
- Spec senza versioning strategy
- Breaking changes senza migration path
- Omettere rate limiting
- Esporre dettagli implementativi nell'API surface

## Errori RFC 7807 (template)

```json
{
  "type": "https://api.example.com/errors/validation-error",
  "title": "Validation Error",
  "status": 422,
  "detail": "The 'email' field must be a valid email address.",
  "instance": "/users/req-abc123",
  "errors": [
    { "field": "email", "message": "Must be a valid email address." }
  ]
}
```

Regole: `Content-Type: application/problem+json` · `type` = URI stabile documentata · `detail` leggibile e azionabile · `errors[]` per errori di campo.

## Output checklist (deliverable)

1. Modello risorse + relazioni (diagramma/tabella)
2. Specifiche endpoint con URI e metodi
3. Spec OpenAPI 3.1 YAML
4. Flussi auth/authz
5. Catalogo errori (tutti i 4xx/5xx con URI `type`)
6. Pattern pagination e filtering
7. Strategia versioning e deprecation
8. `npx @redocly/cli lint openapi.yaml` passa senza errori

## Riferimenti

| Topic | File |
|-------|------|
| REST patterns | `references/rest-patterns.md` |
| Versioning | `references/versioning.md` |
| Pagination | `references/pagination.md` |
| Error handling | `references/error-handling.md` |
| OpenAPI | `references/openapi.md` |

Template OpenAPI 3.1 pronto da copiare: `SKILL.md` → sezione "Templates".

Doc ufficiale: <https://jeffallan.github.io/claude-skills/skills/api-architecture/api-designer/>
