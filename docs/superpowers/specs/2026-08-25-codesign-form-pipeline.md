# Co-design Frontend ↔ Pipeline — Spec Addendum

- Date: 2026-08-25
- Status: Proposed
- Parent spec: `docs/superpowers/specs/2026-08-23-llm-hardening-design.md`
- Branch: new work off `dev` (name TBD by owner, e.g. `feature/codesign-form-pipeline`)
- Triggered by: first real E2E trip on the hardened pipeline (Caraibi, `b4fed052`) exposing region-fragmentation, dead flight probes, and frontend/pipeline misalignment.

## Principles (owner-stated)

1. No chat, ever: the LLM lives in a batch backend producing structured output that composes ONE email. Explanations surface inside the email text, not interactively.
2. Minimal form; every remaining field must have a certain consumer in the pipeline.
3. Hard constraints stay structured (selects); everything expressible in prose lives in free_text.
4. Crossing is the value: multiple departures × windows × arrivals are probed and the cheapest wins, always within caps, fully logged.

## Findings from the Caraibi E2E trip (`b4fed052`)

| # | Finding | Severity |
|---|---------|----------|
| 1 | Region destination ("Caraibi") produced corpus spanning 6+ countries/states — catalog, not roadmap | High |
| 2 | Flight probes ran with raw strings (`departure_id: "Italy"`, `arrival_id: "Caraibi"`) → 0 results, 2 wasted SerpAPI calls | High |
| 3 | 5 of 9 maps corpus items have `link: null` (explore returned a junk item named "Caraibi"); places filters link-less, maps does not | Medium |
| 4 | `travel_mode` never consumed: road-trip requests still trigger flight searches | Medium |
| 5 | `stay_preference` collected but does not steer the places query | Low |
| 6 | `flexible_dates` removal lost real semantics: owner wants dates-as-hard-constraint by default, indicative-and-optimized when flagged | Product decision |

## Part A — Form v2 (docs/index.html)

Final field set (every field ↔ consumer):

| Field | Control | Consumer |
|---|---|---|
| email | input | delivery |
| destination | free text | intent → RESOLVE (if generic region) |
| departure_location | free text | DEPARTURES expansion (multi-airport candidates) |
| start_date / end_date | 2 optional date pickers | period planning (absent) / flight matrix (present) |
| flexible_dates | checkbox, visible only when dates filled | date semantics: hard vs indicative |
| travelers_count | number stepper | prompts (intent + email) |
| travelers_type | select solo/coppia/famiglia/amici/gruppo | prompts |
| budget_amount | optional text, label "Budget (facoltativo)" | prompt email |
| travel_mode | select volo/treno/auto/van/indifferente/**Altro** | flight-matrix GATE |
| stay_preference | select hotel/b&b/agriturismo/glamping/camping/indifferente/**Altro** | places query modifier |
| free_text | textarea | intent extraction |

Removed: `travelers_composition` (redundant prose).

**Altro behavior** (both selects): selecting "Altro" reveals a one-line input; its content is appended client-side into `free_text` (e.g. `"Come viaggia: barca a vela."`), the structured field posts `null`. Zero schema additions.

## Part B — API contract changes

1. **REINTRODUCE `flexible_dates: bool = False`** end-to-end (schemas, trip_store, database column + idempotent `ALTER TABLE trip_history ADD COLUMN IF NOT EXISTS flexible_dates BOOLEAN NOT NULL DEFAULT FALSE;`, orchestrator save). Semantics NOW real (ADR-009):
   - dates absent → period planning chooses windows (unchanged);
   - dates present, flexible=false → HARD constraint, exactly those windows;
   - dates present, flexible=true → INDICATIVE: given windows plus shifted variants probed, cheapest wins (see D2).
2. **REMOVE `travelers_composition`** end-to-end (breaking, same pattern as prior removals; `extra="forbid"` makes old clients fail loudly).
3. Feedback endpoint unchanged (rating 1–5 + comment already supported).

ADRs: `docs/adr/009-flexible-dates-real-semantics.md` (supersedes the relevant part of ADR-007) and extend ADR-008 scope note or create ADR-010 for travelers_composition removal — implementer picks the cleaner option, documenting either way.

## Part C — New/changed pipeline stages

### C1. RESOLVE (new, after INTENT, before EXPLORE)

One `extract()` call → new model `ResolvedDestinations {destinations: list[ResolvedPlace{name, country, airport_code}], rationale}`.

- Triggered when the destination is a GENERIC REGION (LLM judges: "Caraibi", "Sud-Est Asiatico", "Grecia"). Specific cities/places pass through untouched (`resolved = [destination itself]`).
- Chooses 1–2 concrete destinations coherent with the brief (interests/style/season).
- Downstream consumers: explore queries target resolved names; places query uses resolved name(s); flight arrivals use their airport_codes.
- `rationale` persists in package and surfaces in the composed email understanding (compose prompt receives it verbatim).

### C2. DEPARTURES expansion (new, replaces single departure_code usage)

One `extract()` call (merged with C1 into a single "geo planning" call to save latency — implementer decides split vs merged, keeping two schemas) → `DepartureAirports {codes: list[str] /* 1..4 */}` from free-text departure ("Italia" → MXP/FCO/BGY; "Nord Italia" → MXP/LIN/BGY).

### C3. Flight matrix (rework of probing logic)

```
probes = departures(≤3) × windows × arrivals(≤2), capped at MAX_FLIGHT_PROBES = 8
priority order when capping: cover all windows first, then arrivals, then departures
winner = min(price_eur) across all probe results
window counts: absent dates → ≤2 planned windows; hard dates → exactly 1;
flexible dates → up to 3 candidate windows (given + start−7d + start+7d, deduped)
```

- **Gate**: `travel_mode ∈ {auto, van, treno}` ⇒ zero probes, reason logged in tool_calls entry `{engine: "google_flights", skipped: true, reason: travel_mode}`.
- Codes missing entirely after expansion ⇒ zero probes, skip logged (no raw-string calls, ever).
- Every executed probe logged `{engine, params, result_count}` as today.
- Flexible-date shifting (dates present + flexible=true): candidate windows = given window plus start−7d and start+7d variants (deduped, up to 3; the MAX_FLIGHT_PROBES cap with window-first priority governs how many actually run; period-plan fallback unchanged when dates absent).

### C4. Small fixes carried from findings

- maps corpus: drop link-less entries (+log), same rule as places.
- `stay_preference` (when not null/"indifferente"/altro-prose) becomes part of the places query string.
- travelers_count/type already wired (previous cleanup); verify both prompts render them.

## Part D — Post-submit UX

- Polling stays as-is with curated micro-copy per status.
- On DONE: inline feedback row — five stars (1–5) + comment textarea → `POST /api/v1/trips/{id}/feedback`. Owner processes comments from DB with an LLM later (out of scope here).
- No progress-per-stage exposure in this phase.

## Testing strategy

- Unit: RESOLVE pass-through vs resolution; departure expansion caps; matrix capping priority order; travel_mode gate; flexible-window shifting; maps link filter.
- Orchestrator integration: region trip produces constrained searches; road-trip trip logs skipped flights; flexible-dates trip probes ≥2 windows; hard-dates trip probes exactly its window.
- Contract: travelers_composition 422; flexible_dates accepted and persisted.
- UI: manual checklist (Altro reveal + free_text fusion, feedback widget POSTs, checkbox visibility tied to dates).

## Out of scope (later phases)

Knowledge/RAG wiring, budget snapshot section, progress-per-stage UX, hosted trip pages.
