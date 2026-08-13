# ADR-004: API contract (versioning, errors, idempotency) — accepted

## Status
Accepted

## Context
`POST /trips` returns 200 with the created trip and no way for the client to know a
long pipeline is running; errors surface raw exception strings; there is no
versioning; the endpoint is open to anyone (cost-incurring). Fase 4 of the plan
finalizes these.

## Decision
- **Versioning**: prefix API routes with `/api/v1`.
- **Semantics**: `POST /api/v1/trips` returns **202 Accepted** with a `Location`
  header pointing to `GET /api/v1/trips/{id}` (the job is async).
- **Error model**: global handlers returning `application/problem+json` with a typed
  `error_code` (never `str(exc)`), plus a `request_id` middleware.
- **Idempotency**: optional `Idempotency-Key` header deduped server-side.
- **Auth/rate limit**: shared token for the mock frontend + sliding-window rate
  limit; honeypot endpoint for abuse detection.
- **Feedback**: `POST /api/v1/trips/{id}/feedback` upserts a 1-5 rating + optional
  comment (unique on `trip_id`), returning 201.

## Consequences
- Positive: stable contract, actionable errors, safe retries.
- Negative: breaking change for the current mock frontend (`docs/index.html`) — a
  contract test keeps the JSON payload aligned.

## Revisit When
- Real user accounts exist → per-user auth replaces the shared token.