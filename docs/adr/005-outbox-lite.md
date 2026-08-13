# ADR-005: Outbox-lite for email dispatch

## Status
Accepted

## Context
The pipeline sent the email and only then persisted history. A crash or exception
between the two meant the user received an email with no durable record. Full
transactional outbox (a separate dispatcher table + worker that reads pending
outbox rows) was proposed by two of the three reviews.

## Decision
Use **outbox-lite**: reorder the pipeline so the durable record exists **before**
dispatch:
1. compose email content,
2. `save_trip_history(...)` with `status='running'` (upsert, idempotent),
3. send the email,
4. set `status='done'` in Postgres.

A retried job that already persisted history updates the row instead of creating a
duplicate, and the lease (claim + heartbeat) prevents concurrent double-execution
of the same trip. If the email send succeeds but the status update fails, the retry
re-sends — at-least-once, which is the accepted trade-off at this scale.

Rejected: **full transactional outbox** (outbox table + dispatcher). At this scale
(one email per trip, single worker) the extra table and consumer add complexity
without preventing the double-send window either — the dispatcher still has the
same at-least-once delivery problem.

## Consequences
- Positive: "email sent but no record" is impossible; retries are idempotent for
  storage; no extra infrastructure.
- Negative: duplicate email possible in the narrow window between send success and
  status write (rare, bounded by job_timeout + max_tries).
- Risks: none beyond the accepted at-least-once behavior.

## Revisit When
- Multiple emails per trip, or email becomes a financial/legal obligation
  (e.g. invoicing) → adopt the full outbox pattern.