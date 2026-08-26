# ADR-010: Removal of `travelers_composition` — accepted

## Status
Accepted

## Context
The trip form collected both structured travelers fields (`travelers_count`,
`travelers_type`) and a free-text `travelers_composition` prose field ("3
adulti, 2 bambini (6 e 9 anni)"). Since ADR-008 wired the structured travelers
fields into every LLM prompt, the prose field duplicates them with less
fidelity: it overlaps `travelers_count`/`travelers_type`, and anything beyond
them (ages, notes) belongs in `free_text`, which already reaches every prompt.

## Decision
The `travelers_composition` field is removed from the entire stack:
`TripCreateRequest`, the Redis trip record, the intent-extraction and
email-composition prompts, the README/AGENTS curl examples, and (with the
co-design plan's Task 4) the mock frontend form/payload. No database migration
is needed — `trip_history` never had such a column; the field was only carried
in the API schema, Redis record and prompts. Old Redis records that still
contain the key stay parseable because pydantic v2 ignores extra input fields
on read paths.

## Consequences
- Positive: one clear way to express who travels; ages and specifics go to
  `free_text`, which the models already read verbatim.
- **Breaking change** to the `POST /api/v1/trips` contract: payloads carrying
  `travelers_composition` are now rejected with 422 (`extra="forbid"`),
  enforced by a contract test. Old clients fail loudly rather than silently
  losing data.
- The API and the mock frontend must be deployed together (Task 4 removes the
  form input); until then the contract test documents the transitional drift.

## Revisit When
- Traveler details need structure again (e.g. per-traveler ages for pricing);
  at that point prefer typed fields over free-form prose.
