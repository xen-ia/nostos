# ADR-003: Renewable lease for trip execution

## Status
Accepted

## Context
`TripStore.claim()` set a Redis lock with a fixed TTL of 300s. The pipeline can run
longer than 300s (2 LLM calls + 3 SerpAPI searches + email), so a second execution
could claim the lock after expiry and run concurrently → duplicate emails. The lock
was also never released on completion.

## Decision
Turn the claim into a **renewable lease**:
- `TripStore.claim()` sets the lock with `NX EX` (unchanged),
- `TripStore.renew()` extends the TTL,
- `TripOrchestrator.run()` spawns a heartbeat task that renews the lease every 60s
  while the pipeline runs,
- the lease is explicitly released in `finally`, and the heartbeat cancelled.

Concurrent double-execution is now only possible if a worker is hard-killed without
the lease expiring, which ARQ's job timeout + max_tries then bounds.

## Consequences
- Positive: no duplicate execution from long pipelines; locks are released promptly.
- Negative: a hard-killed worker leaves the lock for up to 300s (lease TTL).
- Risks: none beyond the documented expiry window.

## Revisit When
- Multiple workers on the same queue (already supported by ARQ) and lease renewal
  must be resilient to worker loss → move lease ownership into Postgres
  (`FOR UPDATE SKIP LOCKED`) as part of making Postgres the scheduler.