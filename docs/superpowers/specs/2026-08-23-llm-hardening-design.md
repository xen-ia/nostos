# LLM Layer Hardening — Design (v2)

- Date: 2026-08-23
- Status: Proposed
- Branch: `fix/llm-hardening` (off `dev`)
- Supersedes: v1 of same date (recalibrated after owner feedback)
- Scope: this spec = Phase 1 (all interventions below). Phase 2 (separate
  spec/branch, later) = knowledge service wired into the targeting context
  pack + budget section.

## Goal and product context

The deliverable is a single email sent at first contact. Its job:

1. Convince the traveler that Nostos proposes a roadmap they could not build
   alone with a generic AI chat session (live SerpAPI data + curated,
   anti-mass-tourism judgment + professional structure).
2. Convert them to "let's proceed with the human travel agent".
3. Serve as the working document for the human agent team who builds the real
   trip.

There are no live users: quality is judged by the owner and team via manual
try-and-error on real trips. Observability of what the LLM was given and
produced is a first-class requirement.

## Findings from a real production trip (New York, `016aaba9`)

| # | Finding | Severity |
|---|---------|----------|
| 1 | Email cites "Museum of Modern Art", NOT in the researched package (hallucinated resource + invented link) | Critical |
| 2 | Email claims the user asked for "glamping"; no such preference exists (invented preference) | High |
| 3 | `flights: []` — no dates provided → no flight search ever runs | High |
| 4 | POIs are top-3 generic Google results against an anti-mass-tourism brief; maps used with ONE query, places with ONE query, tools never inform each other | High |
| 5 | A stay result has `link: null` → broken card if selected | Medium |
| 6 | No per-trip record of searches performed (inputs/outputs) | Medium |
| 7 | Fixed output shape (forced mix of flight/map/place) forces weak items into the email | High |
| 8 | `flexible_dates` flag is dead weight: stored everywhere, read by nothing | Medium |

## Design principles

- The LLM produces only **decisions/structure** and **verbatim citations** of
  facts present in researched data. Facts enter exclusively through tool
  results. A deterministic validation gate enforces this.
- Research is a **bounded deterministic sequence** (explore → target →
  execute), not an open agent loop: intelligence in *what* is searched, fixed
  *order*, capped calls, everything logged.
- The email shape follows the data: **no fixed quotas**. Sections render only
  when they contain grounded items.

## Stage pipeline (replaces `_compose_package`)

```
INTENT        LLM -> TripIntent (unchanged shape)
PERIOD PLAN   only when start/end dates absent:
              LLM -> PeriodPlan {windows: max 2 x {start, end, rationale}}
              today's date injected; past windows rejected; season sense
              comes from model knowledge now, knowledge base later (Phase 2)
EXPLORE       1 broad maps query ("neighborhoods & key landmarks of X")
              -> anchors: areas, place types, signals
TARGET        LLM receives context pack [anchors] (+ knowledge insights in
              Phase 2) + brief -> proposes 2-4 targeted maps/places queries,
              each derived from anchors (drift capped)
EXECUTE       targeted maps queries + stays aligned to chosen window
              + flights probed across candidate windows -> cheapest wins;
              stays without link dropped; corpus built (merged, deduped,
              capped at 8/category)
CURATE        LLM picks per merit, NO fixed quotas (0-3 per category);
              output references corpus indices only
COMPOSE       LLM writes subject/opening/understanding citing curated IDs
VALIDATE      deterministic gate (see F1)
RENDER/SEND   sectioned template; sections only when non-empty
              + sources appendix (see F6)
```

Orchestrator methods renamed accordingly: `_plan_period`, `_explore`,
`_target`, `_execute_searches`, `_curate`, `_compose_email`,
`_validate`. `_compose_package` disappears.

Budget guardrails: max 2 candidate windows, max 4 targeted queries, ≤ ~8
SerpAPI calls total, shared `serpapi_timeout`; every call logged.

## Interventions

### F1 — Validation gate

New file `src/core/validation.py`, pure functions, no I/O:

- `build_allowed_resources(flights, maps, places) -> list[dict]`.
- `validate_resources(resources, allowed) -> ValidationReport`: match by link
  equality (primary) or name equality (fallback); reports matched/invalid.

Orchestrator: after composition, drop invalid resources (log them); proceed if
≥1 valid remains; else retry once with rejection feedback appended to the
prompt; still zero → trip fails with explicit error (consistent with
`NoResourcesError`).

### F2 — Prompt hardening

Files: `src/core/prompts/__init__.py`, `system_prompt.md`. `EmailContent`
schema unchanged (Ollama grammar compatibility).

- Corpus items rendered with explicit IDs (`[F1]`, `[M1]`, `[P1]`, ...),
  verbatim name/price/link; resources MUST reference ONLY provided IDs.
- Free text quoted verbatim; rule: never state a preference not present in
  structured fields or free text; "not specified" stays unspecified.
- Removed: forced "THREE items" rule and any category quota. New rule: choose
  only what deserves to be shown; omit categories with nothing worthwhile.

### F3 — Period planning replaces crude date fallback

File: `src/core/orchestrator.py` (+ `PeriodPlan` model in `src/core/models.py`).

- Dates present → skipped entirely (current behavior preserved).
- Dates absent → `PeriodPlan` proposes up to 2 future windows (with today's
  date in the prompt; validator rejects past/start>end windows; fallback
  window today+14→today+21 if the plan is unusable).
- Flights probed per window; cheapest selected; stays aligned to the winning
  window. All probes logged in `tool_calls`.

### F4 — Sequential research: explore → target → execute

Files: `src/services/tools/maps.py`, `places.py`, `flights.py`,
`src/core/orchestrator.py`, `src/core/prompts/__init__.py`,
`src/core/models.py`.

- `maps.research` generalized to accept arbitrary queries (list of angles);
  results merged, deduped by name/link, capped at 8.
- EXPLORE runs one broad query producing anchors (areas/types).
- TARGET: one `extract()` call -> new model `TargetQueries {queries: max 4,
  each tied to an anchor}`. In Phase 2 the context pack gains knowledge
  insights ahead of anchors — insertion point pinned, no redesign later.
- EXECUTE: targeted maps queries; stays queried with winning window; flights
  across candidate windows (cheapest wins). Link-less stays dropped + logged.
- New curation step: `Curation` model (selected corpus indices per category +
  short rationale), picks by merit with no quotas.

### F5 — Tool I/O logging without migration

File: `src/core/orchestrator.py` only.

- Every SerpAPI call records `{engine, params (key redacted), result_count}`
  into `package["tool_calls"]`; the capped corpus persists in `package_json`.
  Team sees inputs, outputs, and what was chosen vs available.
- Zero schema changes.

### F6 — Variable-shape email + sources appendix

Files: `src/services/templates/email.html`, `src/services/apis/email.py`,
`src/core/orchestrator.py`, prompts.

- Sectioned rendering: flights / stays / things-to-do sections appear ONLY
  when curated items exist for them. Hard floor: ≥1 resource overall, else the
  trip fails (existing semantics).
- Below the curated cards, a **sources appendix**: the full capped corpus
  grouped by category, each entry name + verbatim link, plus the source-search
  links already returned by SerpAPI (e.g. `google_flights_url`). Implemented
  as `<details>/<summary>` progressive enhancement — collapses where
  supported (Apple Mail, Thunderbird), renders open-but-muted where not
  (Gmail/Outlook strip interactivity). Plain-text version gets a short
  "Fonti esplorate" pointer list.
- Purpose: research effort becomes visible → instrument seriousness, trust.

### F7 — Remove `flexible_dates` end to end (breaking contract)

Files: `src/core/schemas.py`, `src/services/trip_store.py`,
`src/infrastructure/database.py`, `src/core/orchestrator.py`,
`schema.sql`, `docs/index.html`, `tests/test_contract.py`, `tests/fakes.py`,
README examples.

- Semantics after removal: dates present = constraint honored; dates absent =
  period planning chooses (F3).
- DB: remove column from `schema.sql` CREATE TABLE; ship idempotent manual
  migration `ALTER TABLE trip_history DROP COLUMN IF EXISTS flexible_dates;`
  applied per repo convention (no migration tooling).
- Contract: breaking API change → amend ADR-004 (or add ADR-007) documenting
  removal + new date semantics; frontend form loses the checkbox; README curl
  examples updated.
- Deploy note: ship API + frontend together; old Redis trip records tolerate
  the missing field (pydantic ignores extras).

## What we deliberately do NOT do

- No open agentic loop: the sequence is fixed; revisit only if targeted
  queries prove insufficient.
- No Qdrant/vector RAG (Phase 2 uses ADR-006 option B).
- No budget snapshot section (Phase 2).
- No hosted trip page for the appendix (the appendix travels inside the
  email).

## Testing strategy (TDD, RED→GREEN per intervention)

- `tests/test_validation.py` (new): pass/invented/mismatch cases; window
  sanity checks for PeriodPlan.
- Orchestrator tests: invalid resources dropped / retry / fail paths;
  `tool_calls` populated; corpus + curated selection persisted; stage methods
  called in order (explore before target before execute).
- Flights: probes per candidate window; cheapest selected; no-date trips get
  windows from PeriodPlan (fake LLM), usable-fallback path covered.
- Maps/places: multiple angles issued, dedup + cap, link-less stays excluded.
- Email: sections omitted when empty; appendix contains full corpus links;
  plain-text variant updated.
- Contract/store/db tests updated for flexible_dates removal.
- Full suite green per round; one real E2E trip on the VM after merge to dev.

## Success criteria

- Automated: tests above green.
- Manual: owner/team review of real trips via `package_json`: zero
  cited-nonexistent resources, zero invented preferences, sensible periods on
  dateless trips, POIs plausibly aligned with brief, email shape driven by
  data quality (no filler items), sources appendix complete.

## Revisit when

- Targeted queries still generic → reconsider bounded research loop.
- Phase 2 lands → knowledge insights feed PERIOD PLAN and TARGET.
- Appendix UX feedback → consider hosted public trip page.
