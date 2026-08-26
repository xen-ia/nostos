# ADR-009: `flexible_dates` restored with real semantics — accepted

## Status
Accepted. Supersedes the removal decision in
[ADR-007](007-period-planning-and-flexible-dates-removal.md) (the period-planning
half of ADR-007 remains in force).

## Context
ADR-007 removed `flexible_dates` because it was a dead flag stored everywhere
and read by nothing. The removal, however, also discarded a product requirement:
the traveler must be able to say whether given dates are a hard constraint or an
indication. With dates absent, ADR-007's period planning already covers the
"system chooses" case; what is missing is the distinction between hard and soft
dates when they *are* provided.

## Decision
`flexible_dates: bool = False` is reintroduced end to end (`TripCreateRequest`,
the Redis trip record, the Postgres `trip_history` column via idempotent
`ALTER TABLE trip_history ADD COLUMN IF NOT EXISTS flexible_dates BOOLEAN NOT NULL DEFAULT FALSE;`
— applied manually per repo convention — and the orchestrator's history save).
The flag carries real semantics — three date modes:

1. **Dates absent** → period planning proposes windows (unchanged, ADR-007).
2. **Dates present, `flexible_dates=false`** → hard constraint: the pipeline
   plans within exactly those dates.
3. **Dates present, `flexible_dates=true`** → indicative: the system may probe
   shifts of ±7 days around the given window to find better prices or fits.

The flight-probing logic that consumes mode 3 lands with the flight-matrix work
(plan `2026-08-25-codesign-form-pipeline`, Task 3); this change restores the
flag and its persistence so that contract, store, database and frontend evolve
together.

## Consequences
- Positive: date handling expresses all three product modes; the flag is no
  longer dead weight once Task 3 lands.
- **Breaking-change reversal**: `flexible_dates` is accepted again by
  `POST /api/v1/trips`; payloads without it default to `false` (hard dates), so
  existing correct clients keep working.
- Databases that ran the ADR-007 migration need the idempotent re-add above.
- Old Redis records without the key read back as `false`.

## Revisit When
- Flexible probing needs finer granularity than ±7 days (e.g. user-chosen
  tolerance).
