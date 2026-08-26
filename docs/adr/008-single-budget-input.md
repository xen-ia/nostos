# ADR-008: Single budget input and removal of `budget_range` — accepted

## Status
Accepted

## Context
The trip form collected two near-identical budget fields: a structured
`budget_range` select (`economico` / `medio` / `alto` / `no-limit`) and a free-text
`budget_amount`. The structured field was stored end to end (API schema, Redis
trip record, Postgres `trip_history`) but read by no pipeline logic — it never
reached any LLM prompt and duplicated what `budget_amount` already captures,
with less fidelity (see the LLM-hardening review). At the same time, two other
structured inputs — `travelers_count` and `travelers_type` — reached the API but
were likewise missing from every prompt, so the models could not use them.

## Decision
- The single source of truth for budget is the free-text `budget_amount`
  input. The `budget_range` field is removed from the entire stack:
  `TripCreateRequest`, the Redis trip record, the orchestrator's history save,
  the Postgres `trip_history` column, the mock frontend form/payload, and the
  README/AGENTS curl examples. Existing databases are migrated with
  `ALTER TABLE trip_history DROP COLUMN IF EXISTS budget_range;`
  (idempotent, applied manually per repo convention). Old Redis records that
  still contain the key stay parseable because pydantic v2 ignores extra input
  fields on read paths — no store migration is needed.
- `travelers_count` and `travelers_type` are now wired into both LLM prompts:
  the intent-extraction prompt (`build_intent_prompt`) and the email-composition
  prompt (`build_email_prompt` TRIP CONTEXT block).

## Consequences
- Positive: one budget field instead of two redundant ones; travelers fields
  actually influence intent extraction and email tone/grouping.
- **Breaking change** to the `POST /api/v1/trips` contract: payloads carrying
  `budget_range` are now rejected with 422 (`extra="forbid"`), enforced by a
  contract test. Old clients fail loudly rather than silently losing data.
- The API and the mock frontend must be deployed together (the frontend no
  longer sends the field).
- Existing deployments need the manual SQL migration before upgrading.

## Revisit When
- Budget needs to become a first-class constraint for search filtering
  (e.g. flights/stays capped by amount); at that point it should be parsed from
  `budget_amount`, not reintroduced as a separate select.
