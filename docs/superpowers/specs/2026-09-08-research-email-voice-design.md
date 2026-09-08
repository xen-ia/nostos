# Research, Email & Voice Redesign — Design Spec

**Date:** 2026-09-08
**Status:** Awaiting user review
**Scope:** Orchestrator research pipeline, email delivery, voice composer, trip creation contract

## 1. Background & Evidence

Production feedback (trip `9c7e2f66`, Italy → Scotland, van rented on arrival) proved three defects:

1. The LLM extracted `departure_airport_code: FCO` + `destination_airport_code: EDI`, but the hardcoded
   gate vetoed the search: `skipped_flights_reason: "travel_mode:van_life"`. Rigid taxonomy overrode model knowledge.
2. Corpus contained a `facebook.com` POI link that reached the email; `places` was empty with no retry;
   mode-enriched queries were ~20-word keyword stuffing.
3. Email links unusable on mobile Gmail (desktop OK); appendix was an 8-link raw dump; van section redundant.

## 2. Guiding Principles

- **P1 — LLM decides, code executes.** No hardcoded geography/taxonomy gates (`FLIGHT_BLOCKING_TRAVEL_MODES`,
  `_CONTINENT_MAP` are deleted). The model separates *"how I get there"* from *"how I move locally"*.
- **P2 — Mirror a skilled human researcher.** Multi-airport cheap-flight search faithful to dates;
  must-see overview matched to interests, then activity spots; stays by travel mode with fallback.
- **P3 — Email is the product surface.** It must work on mobile Gmail first, degrade gracefully to text.
- **P4 — Voice is Operate mode.** Task completion without learning; everything editable afterwards.
- **P5 — No new LLM calls.** All new decisions ride the existing intent extraction.

## 3. Workstream A — LLM-first flights & research quality

### 3.1 Flight decision

- New `TripIntent` fields: `needs_flights: bool` + `flight_rationale: str` (Italian).
- Intent prompt instructs: separate arrival transport from local mobility. Signals for true:
  different country, islands, "rent on arrival" phrasing, long distance. Doubt rule: different
  countries → true.
- `_execute_searches`: probe flights iff `needs_flights AND departures AND arrivals`.
  Skipped reasons: `"no_flights_needed"` (LLM decision, with rationale logged into `geo_block`
  as `flight_rationale`) or `"no_airports"`.
- Geo prompt extended: departure expansion includes nearby secondary / low-cost airports
  (e.g. North Italy → MXP + BGY + VRN), still max 4 codes, never invented.
- Flexible dates keep the existing ±7d window probing (now actually reachable); fixed dates probe exactly.
- Curation prompt already mandates flights for long-distance trips — unchanged and now consistent.
- Email/curation place flights under "Come arrivare", distinct from local mobility.

### 3.2 Query quality

- Delete `_enrich_queries_for_mode` (mechanical keyword stuffing).
- Add one mode-guidance line to `build_target_prompt`: when `travel_mode` is van/road/sailing,
  the model writes queries ending with a single qualifier (e.g. `campervan parking`, `campsite`).
- Target flow becomes two-phase via prompt: (1) must-see overview of the region matched to interests,
  (2) activity spots (whale watching, hiking, …). Still max 4 queries.
- KB seam: corpus assembly keeps a named insertion point for the curated KB (wired by the
  separate `feature/knowledge-rag` branch); this spec does not wire it.

### 3.3 Corpus hygiene

- Central `JUNK_DOMAINS = {"facebook.com","instagram.com","tiktok.com","twitter.com","x.com",
  "youtube.com","youtu.be"}` (subdomain-aware) applied to maps+places items before `dedupe_cap`.
  Tripadvisor and real-content aggregators stay.
- Places fallback: if `stays` is empty, one retry with generic `hotels in {destination}`, logged
  in `tool_calls`. A real hotel beats an empty "where to stay".
- Curation `pick()` guard unchanged; add curated-counts info log.

### 3.4 Acceptance (A)

- Scotland-style trip (departure country ≠ destination country, "rent on arrival") yields
  `skipped_flights_reason: null` and a "Come arrivare" flight in the email.
- Same-city/region road trip with `needs_flights=false` skips with reason `"no_flights_needed"`.
- No corpus item with junk domain; no enriched query longer than model-written + 1 qualifier.
- Zero new LLM calls per trip; SerpAPI probes still capped.

## 4. Workstream C — Email delivery redesign

Same tech (`string.Template`), new structure. Robustness rules (apply everywhere):
no `details/summary`, no block-anchor-only cards, no gradient as sole visual vehicle,
tap targets ≥ 44px, dark-mode `d-*` classes verified, dignified text part.

### 4.1 Structure

1. Opening (unchanged — product voice).
2. "Come arrivare" hero flight card + bulletproof button "Vedi il volo" (only when flights exist).
3. "I punti di partenza": max 3 cards; each card has an explicit underlined title link PLUS
   a "Apri →" link row (dual click mechanism, never whole-card-anchor only).
4. Travel box (van/road/sailing): compact, mobility merged into one line, no duplicates.
5. Sources: max 5 junk-filtered links, plain list with sober heading, no collapsible.
6. Two stacked (mobile) / side-by-side buttons: "Rispondi per continuare" (`mailto:`) +
   "Lascia un feedback" (token link). Both bulletproof table buttons.
7. Footer with the URL also in plain visible text (copyable even if anchors fail).
8. Text part rewritten: clean sections, one URL per line (auto-linked everywhere),
   same information hierarchy as HTML.

### 4.2 Clickability (C1)

Root cause unconfirmed (desktop Gmail works). The redesign structurally eliminates all four
code-level suspects (block anchors, sub-44px targets, details/summary, gradient-only visuals).
If anything remains unclickable on mobile after this, capture Gmail "Show original" source
and diagnose the client — template work stops guessing at that point.

### 4.3 Acceptance (C)

- Renders with zero `<details>`, zero whole-card-only anchors, all CTA targets ≥ 44px.
- Appendix ≤ 5 links, none from junk domains; no untitled leftover group.
- Text part mirrors HTML hierarchy with bare URLs on their own lines.
- Existing rendering tests + new tests for structure invariants pass.

## 5. Workstream D — Modern voice composer

Unified `free_text` composer in `docs/index.html`; existing palette and ticket layout untouched.

### 5.1 Interaction (WhatsApp-identical)

- Press-and-hold mic to record, release to keep; lateral slide past threshold = cancel (visual hint);
  slide-up = lock for long dictations, tap to stop.
- Keyboard: hold Space on focused button records (`preventDefault`), Esc cancels.
- Live waveform + timer while holding; interim tokens stream into the composer in grey-italic
  with `aria-live="polite"`; finals commit as normal text.

### 5.2 Engines

- Chromium: Web Speech API (`lang="it-IT"`, `interimResults=true`, `continuous=true`) with
  auto-restart while still holding (Chrome ends sessions on long pauses).
- Safari/Firefox (no Web Speech): same holding UI with real analyser waveform but no live tokens,
  then existing batch `POST /api/v1/stt` (`gpt-transcribe`) with an honest "Trascrizione…" state.

### 5.3 Text handling & layout

- Append via `setRangeText` (preserves native Ctrl+Z undo); caret at end after release.
- Auto-grow to ~7 rows, internal scroll beyond; subtle counter near the 5000-char limit.
- Chips stay; known limitation documented: chip toggle-removal may not match dictated text.
- Errors: permission-denied shows re-enable instructions; mid-dictation network failure keeps
  partial text + retry, never discards.

### 5.4 Acceptance (D)

- Full dictation keyboard-free on Chrome; same flow via batch on Safari.
- Undo works after release; Esc/slide cancels without residue; denied permission is recoverable.
- No emoji state icons anywhere in the flow.

## 6. Workstream E — Partial-request contract

- `POST /api/v1/trips` returns 422 when both `destination` and `free_text` are blank
  (mirrors the frontend rule; covers curl/API users). Italian error message.
- No vagueness gate beyond that: period-plan + geo-resolve already handle thin briefs,
  and an LLM clarity judge would be the rigid taxonomy P1 forbids.
- Contract test extended for the 422 case.

## 7. Non-goals

- KB wiring (separate branch), standalone trip page (future email evolution),
  server-side streaming STT (cost; revisited only if Web Speech proves insufficient),
  live submit-button disabling, chip-matching on dictated text.

## 8. Files & Interfaces (for the plan)

- Modify: `src/core/models.py` (`needs_flights`, `flight_rationale`),
  `src/core/prompts/__init__.py` (intent + geo + target prompts),
  `src/core/orchestrator.py` (gate removal, junk filter, places retry, appendix cap),
  `src/services/apis/email.py` + `src/services/templates/email.html` (redesign),
  `src/services/tools/` (filter location if shared), `src/api/routers/trips.py` (422),
  `src/core/schemas.py` (validator), `docs/index.html` (composer).
- Delete: `FLIGHT_BLOCKING_TRAVEL_MODES`, `_CONTINENT_MAP`, `_continent`,
  `_enrich_queries_for_mode`.
- Tests: intent/flight-decision tests, junk-filter tests, email structure invariants,
  contract 422 test, manual browser matrix (Chrome/Safari, mobile/desktop).
