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
- **Auth/rate limit**: `POST /api/v1/trips` is **public** — gated by the email whitelist
  (`email_whitelist` table, 403 `not_whitelisted`) + per-email daily cap + sliding-window rate
  limit. `GET /api/v1/trips/{id}` and feedback stay behind the shared Bearer token (the mock
  frontend only ever POSTs, so no token needs to be exposed in a public page); honeypot
  endpoint for abuse detection.
- **Feedback**: `POST /api/v1/trips/{id}/feedback` upserts a 1-5 rating + optional
  comment (unique on `trip_id`), returning 201.

## Consequences
- Positive: stable contract, actionable errors, safe retries; the shared token is no longer
  exposed to end users of the public page.
- Negative: POST relies on the whitelist + rate limits for abuse protection (anyone can POST,
  but only whitelisted emails create trips and are capped daily).
- Breaking change for the current mock frontend (`docs/index.html`) — a contract test keeps the
  JSON payload aligned.

## Revisit When
- Real user accounts exist → per-user auth replaces the shared token.