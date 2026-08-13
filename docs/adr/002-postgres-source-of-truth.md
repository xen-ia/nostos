# ADR-002: Postgres is the source of truth for trip state

## Status
Accepted

## Context
Trip state lived only in Redis (`trip:{id}` hash with 24h TTL). After expiry the
trip vanished even though the email had been sent. `trip_history` in Postgres was
written only after email dispatch, so a crash between send and save lost the record
("email sent but no history").

## Decision
Postgres `trip_history.status` is the durable source of truth for trip state.
Redis keeps the fast path: `trip:{id}` hash with a short TTL as a cache for `GET`,
and the ARQ queue for pending jobs. `TripOrchestrator.run()` now:
1. persists history with `status='running'` **before** sending the email (outbox-lite, ADR-005),
2. sets `status='done'`/`'error'` in Postgres after dispatch or on failure,
3. mirrors the status to the Redis hash as a cache.

`Database.save_trip_history` is an upsert (`ON CONFLICT (id) DO UPDATE`) so retried
jobs do not create duplicates.

## Consequences
- Positive: no data loss on crash; state survives Redis expiry; history rows now
  also record failures (status column), enabling the feedback table and reporting.
- Negative: two stores to keep in sync; status is written twice (DB + Redis cache).
- Risks: stale Redis cache — accepted, TTL is short and `GET` falls back to 404
  only after expiry.

## Revisit When
- The API needs to read trips older than the Redis TTL → make `GET` query Postgres
  instead of the cache (Fase 4).