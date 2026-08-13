# ADR-001: Durable job queue (ARQ on Redis)

## Status
Accepted

## Context
`POST /trips` ran the whole pipeline (LLM intent, 3 SerpAPI calls, email composition,
Resend send, Postgres history) inside FastAPI `BackgroundTasks` — in-process, not
durable, impossible to retry or scale out. A restart lost in-flight trips; a
crash after the email was sent but before history was saved lost the record.

## Decision
Use **ARQ** (asyncio job queue on the Redis instance already in use) as the durable
job queue. `POST /trips` now only creates the trip and enqueues a `run_trip_job`
job; a separate `src/worker.py` process consumes jobs and runs `TripOrchestrator.run`.

Chosen over:
- **Redis Streams by hand** — ARQ provides retries, timeouts, health checks, worker
  scaling out of the box; writing that ourselves is a waste.
- **Celery** — heavier, needs a broker abstraction and beats-on-process model that
  doesn't fit an all-async FastAPI app at this scale.

## Consequences
- Positive: durable execution, retries (`max_tries=3`), worker can scale horizontally,
  API stays fast (enqueue only).
- Negative: requires running a separate worker process; Redis becomes a second
  operational dependency for job state.
- Risks: job re-delivery is at-least-once — mitigated by idempotent storage (ADR-002)
  and the lease (see ADR-005).

## Revisit When
- >100 jobs/s, or multiple consumer groups needed → consider Redis Streams groups.
- Team wants a single deployable unit → the worker can be a separate container
  behind the same compose file (Fase 5).
