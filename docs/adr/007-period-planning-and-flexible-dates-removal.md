# ADR-007: Period planning and removal of `flexible_dates` — accepted

## Status
Accepted

## Context
The `flexible_dates` flag has been stored end to end (API schema, Redis store,
Postgres `trip_history`, frontend checkbox) but is read by no logic — it is dead
weight (see the LLM-hardening review,
`docs/superpowers/specs/2026-08-23-llm-hardening-design.md`). At the same time
the pipeline gains period-planning semantics: when a trip request carries no
dates, the LLM proposes suitable travel windows instead of failing or guessing.

## Decision
- **Dates present** in the request are a hard constraint: the pipeline plans
  within them.
- **Dates absent**: the pipeline triggers LLM period planning and proposes
  windows.
- The `flexible_dates` field is removed from the entire stack:
  `TripCreateRequest`, the Redis trip record, the Postgres `trip_history`
  column, the orchestrator's history save, and the mock frontend form/payload.
  Existing databases are migrated with
  `ALTER TABLE trip_history DROP COLUMN IF EXISTS flexible_dates;`
  (idempotent, applied manually per repo convention). Old Redis records that
  still contain the key stay parseable because pydantic v2 ignores extra input
  fields on read paths — no store migration is needed.

## Consequences
- Positive: one less dead field to keep consistent across API, store, DB and UI;
  date handling has a single clear rule.
- **Breaking change** to the `POST /api/v1/trips` contract: payloads carrying
  unknown fields (including `flexible_dates`) are now rejected with 422
  (`extra="forbid"`), enforced by a contract test.
- The API and the mock frontend must be deployed together (the frontend no
  longer sends the field).
- Existing deployments need the manual SQL migration before upgrading.

## Revisit When
- Period planning needs user-visible confirmation (proposed windows surfaced in
  the email/API for approval).
