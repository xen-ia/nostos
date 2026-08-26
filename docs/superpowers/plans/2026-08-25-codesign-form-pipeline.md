# Co-design Form ↔ Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Converge the minimal form with the pipeline: RESOLVE stage for generic regions, multi-airport flight matrix with travel_mode gate, real flexible_dates semantics, Altro select pattern, and a feedback widget.

**Architecture:** One new "geo planning" LLM step (resolve + departure expansion) feeds the existing staged pipeline; flight probing becomes a capped, prioritized, fully-logged matrix; the form keeps only fields with certain consumers.

**Tech Stack:** Python 3.13, pydantic v2, pytest-asyncio (`asyncio_mode=auto`), vanilla single-file frontend (docs/index.html), FastAPI feedback endpoint (existing).

**Spec:** `docs/superpowers/specs/2026-08-25-codesign-form-pipeline.md`

## Global Constraints

- `uv run pytest` green before any commit proposal; no linter exists.
- English code/docs; Italian only in user-facing copy. NO git commit by implementers — owner commits; propose strings.
- No chat/interactive LLM output anywhere: all explanations surface inside composed email text.
- Constants module-level in orchestrator: `MAX_FLIGHT_PROBES = 8`, `MAX_DEPARTURE_AIRPORTS = 4`, `MAX_RESOLVED_DESTINATIONS = 2`, `FLEXIBLE_WINDOW_SHIFT_DAYS = 7`.
- Never call SerpAPI flights with non-IATA strings; skips are logged as tool_calls entries with `"skipped": true, "reason": ...`.
- Working tree starts from uncommitted budget-cleanup changes on `feature/codesign-form-pipeline`; diffs are cumulative — reviewers get that context.
- `extra="forbid"` stays on TripCreateRequest: removing travelers_composition breaks old clients by design.

---

### Task 1: Contract — flexible_dates back (real semantics) + travelers_composition out

**Files:**
- Modify: `src/core/schemas.py` (add `flexible_dates: bool = False` after end_date; remove `travelers_composition`)
- Modify: `src/services/trip_store.py` (write+read flexible_dates; remove travelers_composition both directions)
- Modify: `src/core/orchestrator.py` `_save_history` kwargs
- Modify: `src/infrastructure/database.py` + `tests/test_database_sql.py` expected column list (17 columns now)
- Modify: `schema.sql` (re-add column in CREATE TABLE + idempotent `ALTER TABLE trip_history ADD COLUMN IF NOT EXISTS flexible_dates BOOLEAN NOT NULL DEFAULT FALSE;`)
- Create: `docs/adr/009-flexible-dates-real-semantics.md` (supersedes ADR-007's removal decision; documents the three date modes) and `docs/adr/010-travelers-composition-removal.md`
- Modify: `README.md`, `AGENTS.md` curl examples (add flexible_dates where dates present; drop travelers_composition)
- Modify tests: `test_contract.py` (flexible_dates accepted+persisted round-trip; travelers_composition → 422), `fakes.py` make_trip, other touched tests

**Interfaces produced:** `TripCreateRequest.flexible_dates: bool = False`; DB column restored; `travelers_composition` gone everywhere.

- [ ] TDD: contract test for 422 on travelers_composition first (red), then removals/additions (green). Full suite green.
- [ ] Propose commit:
```
feat!: reintroduce flexible_dates with real semantics, remove travelers_composition (ADR-009, ADR-010)
```

### Task 2: Geo planning models + prompts

**Files:**
- Modify: `src/core/models.py` — append:
```python
class ResolvedPlace(BaseModel):
    name: str = Field(description="Nome della meta concreta (isola, città)")
    country: str = Field(default="", description="Paese/Territorio")
    airport_code: Optional[str] = Field(default=None, description="Codice IATA principale della meta")

class ResolvedDestinations(BaseModel):
    destinations: list[ResolvedPlace] = Field(default_factory=list, description="Max 2 mete concrete; vuota se la destinazione era già specifica")
    rationale: str = Field(default="", description="In italiano: perché queste mete per questo viaggiatore")

class DepartureAirports(BaseModel):
    codes: list[str] = Field(default_factory=list, description="1..4 codici IATA candidati di partenza")
```
- Modify: `src/core/prompts/__init__.py` — new `build_geo_prompt(trip, intent)` returning ONE prompt asking for BOTH resolutions (region check → resolved destinations with airport codes; free-text departure → candidate IATA codes, max 4). Rules embedded: if destination is specific, return it as single ResolvedPlace with its airport; never invent codes for unplaceable departures (return empty list instead); consider season/brief for destination choice.
- Modify: `build_email_prompt` signature to accept optional `resolve_rationale: str = ""` rendered as a line `Focus scelto dal sistema: {rationale}` so the explanation surfaces in the email.
- Modify: `tests/fakes.py` FakeLLM defaults: `ResolvedDestinations(destinations=[], rationale="")`, `DepartureAirports(codes=[])`; explicit `responses=` supported as today.
- Test: `tests/test_geo_models.py` — defaults dispatch + explicit responses win (mirror Task-2-style tests).

**Interfaces produced:** schemas above; `build_geo_prompt(trip, intent) -> str`; FakeLLM geo defaults.

- [ ] TDD red→green; full suite green.
- [ ] Propose commit:
```
feat(core): geo planning schemas (ResolvedDestinations, DepartureAirports) + unified geo prompt
```

### Task 3: Pipeline — resolve stage, flight matrix, gates, filters

**Files:**
- Modify: `src/core/orchestrator.py`:
  - New `_geo_plan(trip, intent) -> tuple[ResolvedDestinations, list[str]]`: one `extract(prompt, ...)`? Two models one prompt impossible with current extract(prompt, Model) — make TWO extract calls on the same prompt content (acceptable; or build two prompts sharing context). Implementer choice documented; must log both calls in llm.calls via FakeLLM naturally.
  - Effective search destination = resolved names (join " e ") or original destination when no resolution.
  - Flight probing replaced by `_flight_matrix(...)`: builds probe combos per spec priority (windows→arrivals→departures), caps at MAX_FLIGHT_PROBES; **gates**: travel_mode ∈ {auto, van, treno} ⇒ no probes (tool_calls entry `{engine:"google_flights", skipped:true, reason:"travel_mode:<mode>"}`); empty codes ⇒ skip entry reason "no_airports"; flexible dates ⇒ windows = given ±FLEXIBLE_WINDOW_SHIFT_DAYS deduped (≤3); hard dates ⇒ exactly given window; absent dates ⇒ period-plan windows as today.
  - Winner across all probes = min price_eur; corpus flights = [winner]; package gains `geo: {"resolved": ..., "departure_codes": [...], "skipped_flights_reason": str|None}`.
  - places query modifier: stay_preference not in (None,"indifferente") ⇒ query `"{stay_preference} stays in {destination}"` else `"hotels in {destination}"`.
  - maps corpus link-less entries dropped + logged.
- Modify: `tests/test_orchestrator.py` + new `tests/test_flight_matrix.py`:
  - region trip: FakeLLM returns ResolvedDestinations([Santa Lucia UVF]) ⇒ explore/places queries contain "Santa Lucia"; package.geo populated; compose prompt received rationale (assert via FakeLLM.calls).
  - van trip: zero google_flights calls, skip entry logged.
  - hard dates: exactly 1 window probed; flexible: 3 candidate windows deduped; cap: >8 combos → exactly 8 executed, priority respected (windows covered before extra departures).
  - maps link-less dropped.
- Existing orchestrator tests updated where shapes changed (FakeLLM geo defaults keep most passing unchanged).

**Interfaces consumed:** Task 2 schemas/prompts/fakes; existing validation/sanitize_windows/dedupe_cap.
**Interfaces produced:** orchestrator stages above; package["geo"] block.

- [ ] TDD red→green; full suite green.
- [ ] Propose commit:
```
feat(core): RESOLVE stage + capped prioritized flight matrix with travel_mode gate and flexible-date shifting
```

### Task 4: Frontend — form v2 + feedback widget

**Files:**
- Modify: `docs/index.html` (all inline, no build):
  - Remove `travelers_composition` label+input (~line 770s) and its payload line.
  - travel_mode & stay_preference selects: add `<option value="">Altro…</option>`; on change show sibling text input (hidden div); on submit: if Altro selected → append `"Come viaggia: {altro_text}."` / `"Soggiorno: {altro_text}."` to free_text value and post null for the structured field.
  - Re-add flexible_dates checkbox under the date pickers; visible ONLY when start_date filled (small JS listener); posts boolean (default false).
  - Status polling micro-copy: PENDING "Richiesta ricevuta…" / RUNNING "Stiamo esplorando le mete…" / DONE shows feedback row.
  - Feedback widget on DONE: five star buttons (1–5) + textarea + submit → `POST {API_BASE}/trips/{id}/feedback` JSON `{rating, comment}`; success state "Grazie!" inline; errors silent-retry-free but visible.
- Manual checklist (report): fill form → payload JSON correct (Altro fusion, structured nulls, flexible only when dates); DONE → stars+comment POST 201.

No automated UI tests exist — verify via served page (`python -m http.server`) + curl against local API; document in report.

- [ ] Implement + manual checklist in report.
- [ ] Propose commit:
```
feat(frontend): minimal form v2 with Altro pattern, conditional flexible_dates, feedback widget
```

### Task 5: Whole-feature verification

- [ ] `uv run pytest` green.
- [ ] Owner E2E on VM after merge: region trip (Caraibi) → searches constrained to resolved islands, email explains focus; van trip → skipped flights logged; flexible-dates trip → ≥2 windows in tool_calls; feedback POST visible in DB.

## Self-Review

Spec coverage: Part A form→Task 4 (travelers_composition removal backend side in Task 1); Part B contracts→Task 1; C1/C2→Tasks 2-3; C3 matrix/gates/shifting→Task 3; C4 fixes→Task 3; Part D UX→Task 4; verification→Task 5. No placeholders beyond documented implementer choices (single-vs-two geo calls; ADR numbering already pinned).
