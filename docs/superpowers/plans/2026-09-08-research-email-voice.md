# Research, Email & Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the rigid flight gate with an LLM flight decision, clean the research corpus, redesign email delivery for mobile, ship a modern WhatsApp-style voice composer, and enforce the trip-creation contract server-side.

**Architecture:** Backend-first (intent fields → gate removal → query/corpus hygiene), then email template+rendering, then the 422 contract validator, then the vanilla-JS composer. No new LLM calls per trip; SerpAPI probe caps unchanged.

**Tech Stack:** FastAPI + Pydantic, OpenAI/Anthropic/Ollama via `LLMClient.extract`, SerpAPI, Resend, vanilla JS + Web Speech API with MediaRecorder/`gpt-transcribe` fallback.

**Spec:** `docs/superpowers/specs/2026-09-08-research-email-voice-design.md`

## Global Constraints

- Python >= 3.13, run with `uv run <cmd>`, `UV_PROJECT_ENVIRONMENT="$HOME/.venvs/nostos"`, never create `.venv` in the workspace.
- Config via `.env` (`NOSTOS_` prefix) in `src/settings.py`; no new settings in this plan (all defaults already exist).
- Tests: `uv run pytest` (`pythonpath=["."]`, `asyncio_mode=auto`); fakeredis via `tests/fakes.py` (`make_store`, `FakeLLM`, `FakeEmailSender`, `FakeDatabase`, `make_trip`).
- Docs and code comments in English; user-facing copy (email, errors, frontend) in Italian.
- Orchestrator lease (`claim`/`renew`/`release`, 300s TTL) untouched; probe caps (`MAX_FLIGHT_PROBES`, `CORPUS_CAP`) unchanged.
- Contract test `tests/test_contract.py` must pass after every task.
- The two pre-existing date-sensitive tests use relative dates — keep that pattern for any new date fixture.

---

## File Structure

**Modified:**
- `src/core/models.py` — `TripIntent` gains `needs_flights: bool = True`, `flight_rationale: str = ""`.
- `src/core/prompts/__init__.py` — intent prompt gains FLIGHTS block; geo prompt gains secondary-airport expansion; target prompt gains 1-line mode guidance.
- `src/core/orchestrator.py` — gate removal (`FLIGHT_BLOCKING_TRAVEL_MODES`, `_CONTINENT_MAP`, `_continent` deleted); new probe rule; `JUNK_DOMAINS` + corpus filter; places retry; appendix cap; `_compose_body_text` rewrite (text part mirrors HTML hierarchy).
- `src/services/apis/email.py` + `src/services/templates/email.html` — redesign (hero flight, dual-link cards, compact travel box, capped sources, dual bulletproof buttons, plain-text footer URL).
- `src/core/schemas.py` — `TripCreateRequest` 422 validator (destination or free_text required).
- `docs/index.html` — unified voice composer (hold-to-record, live tokens, auto-grow).
- `tests/test_flight_matrix.py` — `test_van_trip_skips_all_flight_probes` updated to the new decision + reason.

**Created:**
- `tests/test_flight_decision.py` — needs_flights probe/skip matrix.
- `tests/test_corpus_hygiene.py` — junk-domain filter + places retry.
- `tests/test_email_structure.py` — HTML structure invariants.

---

### Task 1: Intent fields + prompt guidance for flight decision

**Files:**
- Modify: `src/core/models.py:56-64`
- Modify: `src/core/prompts/__init__.py:33-37`
- Test: `tests/test_flight_decision.py` (new file, first 2 tests only in this task)

**Interfaces:**
- Consumes: nothing new (fields live on the existing `TripIntent` extraction).
- Produces: `TripIntent.needs_flights: bool` (default `True`), `TripIntent.flight_rationale: str` (default `""`) for Task 2.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_flight_decision.py
from src.core.models import TripIntent
from src.core.prompts import build_intent_prompt
from tests.fakes import make_trip


def test_needs_flights_defaults_true_with_empty_rationale():
    intent = TripIntent(destination="Scozia")
    assert intent.needs_flights is True
    assert intent.flight_rationale == ""


def test_intent_prompt_guides_arrival_vs_local_decision():
    prompt = build_intent_prompt(make_trip())
    assert "needs_flights" in prompt
    assert "come arrivo" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_flight_decision.py -v`
Expected: FAIL with `needs_flights` validation error (extra field) or `AttributeError`.

- [ ] **Step 3: Add model fields**

```python
# src/core/models.py — after mobility_preferences field:
    needs_flights: bool = Field(
        default=True,
        description=(
            "True se il viaggiatore deve raggiungere la destinazione con un volo: "
            "paese diverso dalla partenza, isole, 'noleggio quando arrivo', lunghe distanze. "
            "False solo quando è chiaro che resta in zona (stessa regione, on the road da casa). "
            "Nel dubbio con paesi diversi → True."
        ),
    )
    flight_rationale: str = Field(
        default="",
        description="In italiano: perché i voli servono oppure no per questo viaggio",
    )
```

Default `True` preserves current probe behavior for every existing fixture unless the model opts out.

- [ ] **Step 4: Add prompt block**

```python
# src/core/prompts/__init__.py — inside build_intent_prompt, after the TRAVEL MODE & MOBILITY block:
    FLIGHTS (decidi come un ricercatore viaggi esperto — "come arrivo" NON è "come mi muovo in loco"):
    - needs_flights: true se serve un volo per ARRIVARE (paese diverso dalla partenza, isole,
      frasi come 'noleggio quando arrivo'/'noleggio un van lì', lunghe distanze); false solo se
      il viaggio resta chiaramente in zona. Nel dubbio con paesi diversi → true.
    - flight_rationale: una frase in italiano con il perché.
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_flight_decision.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/core/models.py src/core/prompts/__init__.py tests/test_flight_decision.py
git commit -m "feat(intent): needs_flights decision fields + prompt guidance"
```

---

### Task 2: Remove the rigid gate, wire the LLM decision

**Files:**
- Modify: `src/core/orchestrator.py:48-93` (delete map + helper), `src/core/orchestrator.py:475-499` (new rule), `src/core/orchestrator.py:556-561` (geo_block rationale)
- Modify: `tests/test_flight_matrix.py:140-155` (update van test)
- Test: `tests/test_flight_decision.py` (append 3 tests)

**Interfaces:**
- Consumes: `TripIntent.needs_flights`, `TripIntent.flight_rationale` from Task 1.
- Produces: probe iff `needs_flights AND departures AND arrivals`; skip reasons `"no_flights_needed"` / `"no_airports"`; `geo["flight_rationale"]` for Task 5 email + audit.

- [ ] **Step 1: Write the failing tests (append to tests/test_flight_decision.py)**

```python
import pytest
from src.core.models import DepartureAirports, ResolvedDestinations, ResolvedPlace, TripIntent
from tests.fakes import FakeDatabase, FakeEmailSender, FakeLLM, make_store, make_trip
from tests.test_flight_matrix import EMAIL, _patch_searches, _run


def _llm_with_intent(intent):
    return FakeLLM(response=intent, email_response=EMAIL)


async def test_van_life_with_needs_flights_true_probes(monkeypatch):
    trip = make_trip(start_date="2026-09-01", end_date="2026-09-10")
    intent = TripIntent(
        destination="Scozia",
        departure_airport_code="MXP",
        destination_airport_code="EDI",
        travel_mode="van_life",
        needs_flights=True,
        flight_rationale="Volo per arrivare, van noleggiato in loco",
    )
    calls = []

    async def fake_flights(*args, **kwargs):
        calls.append(args)
        return []

    _patch_searches(monkeypatch, flights_fn=fake_flights)
    db = FakeDatabase()
    await _run(trip, _llm_with_intent(intent), db)
    assert calls != [], "needs_flights=true must probe even for van_life"
    assert db.saved[0]["package"]["geo"]["flight_rationale"] == "Volo per arrivare, van noleggiato in loco"


async def test_needs_flights_false_skips_with_reason(monkeypatch):
    trip = make_trip(start_date="2026-09-01", end_date="2026-09-10")
    intent = TripIntent(destination="Lombardia", travel_mode="road_trip", needs_flights=False,
                        flight_rationale="Gita in zona, si va in auto da casa")
    calls = []

    async def fake_flights(*args, **kwargs):
        calls.append(args)
        return []

    _patch_searches(monkeypatch, flights_fn=fake_flights)
    db = FakeDatabase()
    await _run(trip, _llm_with_intent(intent), db)
    assert calls == []
    skips = [tc for tc in db.saved[0]["package"]["tool_calls"] if tc.get("engine") == "google_flights"]
    assert skips == [{"engine": "google_flights", "skipped": True, "reason": "no_flights_needed"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_flight_decision.py -v`
Expected: FAIL — `needs_flights=true` case probes zero (old gate still blocks van_life).

- [ ] **Step 3: Delete the rigid taxonomy**

Delete from `src/core/orchestrator.py`: `FLIGHT_BLOCKING_TRAVEL_MODES` (line 48),
`_CONTINENT_MAP` (lines 50-83), `_continent` (lines 86-93). Then grep the repo for
remaining references: obsolete `_continent` unit tests (e.g. in `tests/test_orchestrator.py`,
`tests/test_feedback_token.py`) must be DELETED, and any test encoding the old gate
(e.g. intercontinental-forces / same-continent-skips tests) must be REWRITTEN to
new-world equivalents (`needs_flights=True` probes / `needs_flights=False` skips).

- [ ] **Step 4: Implement the new rule (replaces lines 475-499)**

```python
        # Flight matrix: the LLM decides per trip (intent.needs_flights); code only executes.
        # Legacy form travel_mode is NOT consulted: a van rented on arrival still needs a flight.
        departures = departure_codes or _valid_iata([intent.departure_airport_code])
        arrivals = (
            _valid_iata([p.airport_code for p in resolved.destinations])
            or _valid_iata([intent.destination_airport_code])
        )
        if not departures or not arrivals:
            skipped_reason = "no_airports"
        elif not intent.needs_flights:
            skipped_reason = "no_flights_needed"
        else:
            skipped_reason = None
```

And in `geo_block` (after `"skipped_flights_reason": skipped_reason,`) add:

```python
            "flight_rationale": intent.flight_rationale,
```

- [ ] **Step 5: Update the existing van test to the new world**

```python
# tests/test_flight_matrix.py — replace test_van_trip_skips_all_flight_probes body expectations:
async def test_van_trip_skips_all_flight_probes(monkeypatch):
    from src.core.models import TripIntent
    trip = make_trip(start_date="2026-09-01", end_date="2026-09-10", travel_mode="van")
    intent = TripIntent(destination="Caraibi", departure_airport_code="MXP",
                        destination_airport_code="HND", travel_mode="van_life",
                        needs_flights=False, flight_rationale="Van da casa, niente volo")
    llm = FakeLLM(response=intent, email_response=EMAIL)
    calls = []

    async def fake_flights(*args, **kwargs):
        calls.append(args)
        return []

    _patch_searches(monkeypatch, flights_fn=fake_flights)
    db = FakeDatabase()
    await _run(trip, llm, db)

    assert calls == [], "needs_flights=false must execute zero probes"
    skips = [tc for tc in db.saved[0]["package"]["tool_calls"] if tc.get("engine") == "google_flights"]
    assert skips == [{"engine": "google_flights", "skipped": True, "reason": "no_flights_needed"}]
    assert db.saved[0]["package"]["geo"]["skipped_flights_reason"] == "no_flights_needed"
```

- [ ] **Step 6: Run tests to verify everything passes**

Run: `uv run pytest tests/test_flight_decision.py tests/test_flight_matrix.py tests/test_orchestrator.py -v`
Expected: PASS. Then full suite: `uv run pytest -q` (137 passed, 1 skipped pre-existing).

- [ ] **Step 7: Commit**

```bash
git add src/core/orchestrator.py tests/test_flight_decision.py tests/test_flight_matrix.py tests/test_orchestrator.py tests/test_feedback_token.py
git commit -m "feat(flights): LLM-driven flight decision replaces rigid travel-mode gate"
```

---

### Task 3: Delete query stuffing, guide target + geo prompts

**Files:**
- Modify: `src/core/orchestrator.py:390-414` (delete `_enrich_queries_for_mode`, call sites use raw queries)
- Modify: `src/core/prompts/__init__.py:75-79` (mode-guidance line in target prompt)
- Modify: `src/core/prompts/__init__.py:132-134` (secondary-airport guidance in geo prompt)
- Test: `tests/test_target_queries.py` (new)

**Interfaces:**
- Consumes: `TripIntent.travel_mode`, `mobility_preferences` (read by the prompt, no longer by code).
- Produces: `TargetQueries` whose queries carry at most one model-written qualifier; `_execute_searches` sends `targeted_queries` to maps verbatim.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_target_queries.py
from src.core.models import TargetQueries, TripIntent
from src.core.prompts import build_geo_prompt, build_target_prompt
from tests.fakes import make_trip


def test_target_prompt_carries_single_qualifier_guidance():
    intent = TripIntent(destination="Scozia", travel_mode="van_life",
                        mobility_preferences=["auto", "van"])
    prompt = build_target_prompt(make_trip(), intent, "- Skye (island)")
    assert "campervan parking" in prompt or "campsite" in prompt
    assert "accessibile auto parcheggio" not in prompt


def test_no_mechanical_enrichment_function():
    import src.core.orchestrator as orch
    assert not hasattr(orch.TripOrchestrator, "_enrich_queries_for_mode")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_target_queries.py -v`
Expected: FAIL — guidance line missing and `_enrich_queries_for_mode` still exists.

- [ ] **Step 3: Delete the enrichment, use raw queries**

In `src/core/orchestrator.py`: delete `_enrich_queries_for_mode` entirely and change the call site:

```python
        # Targeted queries go to maps verbatim: the model already writes mode-aware queries.
        maps_results = await asyncio.gather(*(
            guarded(maps.research(q, timeout=self._serpapi_timeout, api_key=self._serpapi_api_key),
                    "google_maps", {"q": q})
            for q in targeted_queries
        ))
```

- [ ] **Step 4: Add mode guidance to the target prompt + secondary airports to the geo prompt**

Geo prompt addition (spec §3.1 — departure expansion must include nearby secondary/low-cost
airports; this was not part of closed Task 1, it lands here). In `build_geo_prompt`, PART 2
(`DepartureAirports`), after the "1..4 candidate IATA codes" bullet, add:

```
    - Include nearby secondary and low-cost airports besides the main hubs
      (e.g. North Italy → MXP plus BGY and VRN), still max 4 codes total, never invented.
```

And extend the Step-1 test file with:

```python
def test_geo_prompt_asks_secondary_airports():
    from src.core.prompts import build_geo_prompt
    prompt = build_geo_prompt(make_trip(), TripIntent(destination="Scozia"))
    assert "secondary" in prompt
```

Target prompt addition (mode guidance):

In `src/core/prompts/__init__.py`, inside `build_target_prompt` before the closing `"""`,
after the "Each query must derive from an anchor." line, add:

```
    MODE GUIDANCE (apply lightly — at most ONE short qualifier per query):
    - van_life: prefer a trailing qualifier like 'campervan parking' or 'campsite';
    - road_trip: prefer 'scenic drive stops' or 'viewpoint parking';
    - sailing: prefer 'marina' or 'anchorage'.
    Write clean natural queries first; the qualifier is a hint, not a suffix to staple.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_target_queries.py tests/test_orchestrator.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/core/orchestrator.py src/core/prompts/__init__.py tests/test_target_queries.py
git commit -m "feat(research): model-written mode-aware queries, no keyword stuffing"
```

---

### Task 4: Junk-domain filter + places fallback

**Files:**
- Modify: `src/core/orchestrator.py` (new `JUNK_DOMAINS` + `_is_junk_link`, filter in `_execute_searches` corpus assembly; places retry)
- Test: `tests/test_corpus_hygiene.py` (new)

**Interfaces:**
- Consumes: raw `maps_items` / `stays` lists inside `_execute_searches`.
- Produces: corpus maps/places with zero junk-domain links; `stays` retried once with a generic query when empty (logged in `tool_calls` as a second `google_hotels` entry).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_corpus_hygiene.py
from src.core.orchestrator import _is_junk_link


def test_social_links_are_junk():
    assert _is_junk_link("https://www.facebook.com/fairyglenisleofskye")
    assert _is_junk_link("https://m.instagram.com/p/abc/")
    assert _is_junk_link("https://youtu.be/xyz")


def test_real_links_are_not_junk():
    assert not _is_junk_link("https://www.dunvegancastle.com/fairy-pools/")
    assert not _is_junk_link("https://www.tripadvisor.com/Attraction_123")
    assert not _is_junk_link(None)
    assert not _is_junk_link("")
```

Plus an orchestrator-level test (same file):

```python
async def test_places_empty_retries_generic_query(monkeypatch):
    from tests.fakes import FakeDatabase, FakeLLM, make_store, make_trip
    from tests.test_flight_matrix import EMAIL, _run
    from src.core.models import TripIntent

    trip = make_trip(start_date="2026-09-01", end_date="2026-09-10")
    queries = []

    async def fake_places(**kwargs):
        queries.append(kwargs.get("query"))
        if len(queries) == 1:
            return []
        return [{"name": "Hotel Generico", "price_per_night_eur": 80,
                 "link": "https://example.com/hotel"}]

    async def fake_flights(*args, **kwargs):
        return []

    async def fake_maps(query, **kwargs):
        return [{"name": "POI", "type": "t", "rating": 4.5, "link": "https://example.com/poi"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)
    intent = TripIntent(destination="Shetland", accommodation_style="van", travel_mode="van_life")
    db = FakeDatabase()
    await _run(trip, FakeLLM(response=intent, email_response=EMAIL), db)
    assert len(queries) == 2
    assert queries[1].startswith("hotels in ")
    hotels_calls = [tc for tc in db.saved[0]["package"]["tool_calls"]
                    if tc.get("engine") == "google_hotels"]
    assert len(hotels_calls) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_corpus_hygiene.py -v`
Expected: FAIL with `ImportError` (`_is_junk_link` does not exist).

- [ ] **Step 3: Implement filter + retry**

```python
# src/core/orchestrator.py — module level, near FLIGHT constants:
from urllib.parse import urlparse

JUNK_DOMAINS = frozenset({
    "facebook.com", "instagram.com", "tiktok.com", "twitter.com", "x.com",
    "youtube.com", "youtu.be",
})


def _is_junk_link(link: str | None) -> bool:
    """True for social/video links that must never reach an email."""
    if not link:
        return False
    try:
        host = urlparse(link).netloc.lower().split(":")[0]
    except ValueError:
        return False
    return host == "x.com" or any(
        host == d or host.endswith("." + d) for d in JUNK_DOMAINS if d != "x.com"
    )
```

Note: `"x.com"` needs exact match (it would also match via endswith logic, but keep the
explicit short-domain rule simple: exact match for domains of length ≤ 5, suffix match otherwise).
Simpler correct form used above: exact match for `x.com`, suffix-or-exact for the rest.

Filter at corpus assembly (replaces `linked_maps = [...]`):

```python
        linked_maps = [i for i in maps_items if i.get("link") and not _is_junk_link(i.get("link"))]
        dropped_junk = [i.get("name") for i in maps_items
                        if i.get("link") and _is_junk_link(i.get("link"))]
        if dropped_junk:
            logger.warning("maps corpus: dropped %d junk-domain entries: %s", len(dropped_junk), dropped_junk)
```

Places retry (replaces the single `stays = await guarded(...)` call):

```python
        stays = await guarded(
            places.search(destination=destination, query=places_query, check_in_date=check_in, check_out_date=check_out,
                          timeout=self._serpapi_timeout, api_key=self._serpapi_api_key),
            "google_hotels", {"q": places_query, "check_in_date": check_in, "check_out_date": check_out},
        )
        if not stays:
            logger.info("google_hotels: empty for mode query, retrying generic hotels in %s", destination)
            stays = await guarded(
                places.search(destination=destination, query=f"hotels in {destination}",
                              check_in_date=check_in, check_out_date=check_out,
                              timeout=self._serpapi_timeout, api_key=self._serpapi_api_key),
                "google_hotels", {"q": f"hotels in {destination}", "check_in_date": check_in,
                                  "check_out_date": check_out},
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_corpus_hygiene.py tests/test_orchestrator.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/orchestrator.py tests/test_corpus_hygiene.py
git commit -m "feat(research): junk-domain filter + generic hotels retry"
```

---

### Task 5: Email delivery redesign

**Files:**
- Modify: `src/services/templates/email.html` (new structure, same placeholders `$opening`, `$understanding`, `$cta`, `$honest_note`, `$signature_*`, `$feedback_link`; drop `$travel_mode_section`, `$mobility_section`, `$resource_groups`, `$appendix`)
- Modify: `src/services/apis/email.py` (new renderers; delete `_render_mobility_inline` and `<details>` appendix)
- Modify: `src/core/orchestrator.py` (`_build_appendix` cap 5 + junk filter; `_compose_body_text` rewrite mirroring HTML hierarchy)
- Test: `tests/test_email_structure.py` (new)

**Interfaces:**
- Consumes: `content` dict (`opening`, `understanding`, `resources`, `sections_map`, `travel_mode`, `mobility`, `appendix`, `cta`, `feedback_link`), filtered corpus + capped appendix from Task 4/orchestrator.
- Produces: robust mobile-first HTML + clean text part. `geo["flight_rationale"]` is available but NOT rendered (audit only).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_email_structure.py
from src.services.apis.email import build_html_email

BASE = {"opening": "O.", "understanding": "U.", "resources": [], "cta": "C.",
        "honest_note": "N.", "sections_map": {}, "appendix": {"groups": [], "source_links": []}}


def test_no_details_no_block_only_anchors():
    html = build_html_email({**BASE, "travel_mode": "van_life", "mobility": ["auto", "van"],
                             "feedback_link": "https://x.example/f?trip_id=1&token=abc"})
    assert "<details" not in html
    assert "Lascia un feedback" in html
    assert "https://x.example/f?trip_id=1&amp;token=abc" in html


def test_van_mobility_merged_single_line():
    html = build_html_email({**BASE, "travel_mode": "van_life", "mobility": ["auto", "van"]})
    assert html.count("Mezzi") == 1
    assert "Come spostarti" not in html


def test_cta_targets_min_44px():
    import re
    html = build_html_email({**BASE, "feedback_link": "https://x.example/f"})
    pads = re.findall(r"padding:(\d+)px", html)
    cta_pads = [int(p) for p in pads]
    assert cta_pads and min(cta_pads) >= 14  # 14px vertical padding ≈ 44px target with 16px text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_email_structure.py -v`
Expected: FAIL — `<details>` present, single "Mezzi" violated, small CTA padding.

- [ ] **Step 3: Rewrite template structure**

New `src/services/templates/email.html` order, keeping header/opening/signature/footer styling:
`$opening` → `$understanding` → `$arrival_section` → `$resource_groups` → `$travel_box` →
`$sources_section` → dual buttons `$reply_button` + `$feedback_link` → signature → honest note →
footer with `$footer_url_visible` (plain-text URL next to the linked one).
Delete `$travel_mode_section`, `$mobility_section`, `$appendix` placeholders.

- [ ] **Step 4: Rewrite renderers in `src/services/apis/email.py`**

  - `_render_arrival_block(flights)`: hero card for the first flight (`compagnia, tratta, data, prezzo`)
    + bulletproof table button "Vedi il volo". Empty → `""`.
  - Cards: keep `_CARD_TEMPLATE` whole-card anchor BUT add inside it an explicit underlined title link
    (`<a href>` wrapping only the name, `text-decoration:underline`) plus an "Apri →" link row —
    dual click mechanism. Delete `_render_mobility_inline`.
  - Travel box: single block; mobility merged into one line
    (`Ti muoverai in van: auto, van`) — the word "Mezzi" appears at most once per email.
  - Sources: plain `<ul>` of at most 5 links, sober heading, no `<details>`.
  - Buttons: table-based bulletproof (`<table><tr><td bgcolor="#A84E28" style="border-radius:999px;">`
    + `<a style="display:inline-block;padding:14px 26px;font-size:16px;">`), "Rispondi per continuare"
    (`mailto:`) + "Lascia un feedback" (token URL). Delete the old pill.
  - Footer: linked URL + the same URL as visible plain text underneath.
  - `build_html_email` wires the new placeholders; keep `_e()` escaping on every interpolated value.

- [ ] **Step 5: Cap appendix + rewrite text part in orchestrator**

`_build_appendix`: after building groups, junk-filter every item via `_is_junk_link` and cap the
total links across groups at 5 (keep group order Voli → Dove stare → Cosa fare; drop empty groups).

`_compose_body_text` rewrite (same hierarchy as HTML):
opening → blank → understanding → blank → "Come arrivare:" + flight line (if any) →
" Punti di partenza:" + numbered resources with URL on its own line → travel box one-liner →
"Fonti:" + one URL per line → cta → honest note → signature lines.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_email_structure.py tests/test_email_rendering.py tests/test_email_dedup.py -v`
Expected: PASS. (Note: `tests/test_email_dedup.py` expectations still hold — single "Mezzi", no
"Come spostarti" — keep that file green; extend it only if the new box changes the strings.)

- [ ] **Step 7: Commit**

```bash
git add src/services/apis/email.py src/services/templates/email.html src/core/orchestrator.py tests/test_email_structure.py
git commit -m "feat(email): mobile-first redesign, dual links, capped sources"
```

---

### Task 6: Trip-creation contract — 422 on empty brief

**Files:**
- Modify: `src/core/schemas.py:43-47` (extend `_check_date_range` or add new model_validator)
- Test: `tests/test_contract.py` (append) or `tests/test_api.py`

**Interfaces:**
- Consumes: `TripCreateRequest(destination, free_text)`.
- Produces: FastAPI 422 when both are blank (whitespace counts as blank).

- [ ] **Step 1: Write the failing test**

```python
def test_empty_brief_rejected(client):
    resp = client.post("/api/v1/trips", json={"email": "t@t.example"})
    assert resp.status_code == 422
```

(Adapt to the existing client fixture style in `tests/test_api.py`; `free_text` defaults to `""`
so omitting both fields exercises the rule. Also assert a whitespace-only brief 422s.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py::test_empty_brief_rejected -v`
Expected: FAIL with 202 (accepted).

- [ ] **Step 3: Add validator**

```python
# src/core/schemas.py — add after _check_date_range:
    @model_validator(mode="after")
    def _require_brief(self) -> "TripCreateRequest":
        if not (self.destination or "").strip() and not (self.free_text or "").strip():
            raise ValueError("destination or free_text is required: tell us where or what you dream of")
        return self
```

FastAPI renders `ValueError` as 422 automatically. Message in English (API layer); the frontend
keeps its Italian inline copy.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_api.py tests/test_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/schemas.py tests/test_api.py
git commit -m "feat(api): 422 when destination and free_text are both blank"
```

---

### Task 7: Modern voice composer

**Files:**
- Modify: `docs/index.html` (free_text block HTML + JS; existing `#mic-btn`, `#mic-status`, `freeText` const, `API_BASE`, `POST /api/v1/stt` stay)
- Test: `tests/test_contract.py` must stay green + manual browser matrix (below)

**Interfaces:**
- Consumes: Web Speech API (`SpeechRecognition || webkitSpeechRecognition`) when present;
  otherwise MediaRecorder → `POST /api/v1/stt` → `{text}` (existing endpoint).
- Produces: committed Italian text in `#free_text`, undo-safe, auto-grown.

- [ ] **Step 1: Replace the mic block HTML**

Replace the current `#mic-btn` emoji button + `#mic-status` div with:

```html
<div class="voicebar" id="voicebar" hidden>
  <canvas id="voice-wave" width="120" height="28" aria-hidden="true"></canvas>
  <span id="voice-timer" role="timer">0:00</span>
  <span id="voice-hint">Tieni premuto · trascina per annullare</span>
  <button type="button" id="voice-lock" aria-label="Blocca registrazione">🔒 Lock</button>
</div>
```

Style with existing ticket palette (`--terracotta-deep`, `--gold`, parchment). No emoji as state
icons on the mic button itself: inline SVG mic + recording dot.

- [ ] **Step 2: Implement hold-to-record + lock + cancel**

```js
// Press-and-hold on #mic-btn (Pointer Events cover mouse/touch/stylus):
// pointerdown → start (Web Speech if available else MediaRecorder), show #voicebar, start timer+waveform
// pointerup → stop → commit (append via freeText.setRangeText(chunk, selStart, selEnd, "end"))
// pointermove past 60px lateral → cancel mode (hint turns red, release discards, transcript dropped)
// slide-up past 60px OR #voice-lock tap after 1s hold → locked mode (tap mic to stop)
// Keyboard: Space keydown+keyup on focused #mic-btn records; Escape cancels mid-hold.
// All strings Italian. aria-live="polite" region announces "Registrazione avviata / annullata / testo aggiunto".
```

- [ ] **Step 3: Implement live tokens + fallback**

```js
// Web Speech path: rec = new (SpeechRecognition||webkitSpeechRecognition)();
// rec.lang = "it-IT"; rec.interimResults = true; rec.continuous = true;
// onresult: interim spans render grey-italic inside composer overlay; finals commit via setRangeText.
// onend while still holding → rec.start() again (Chrome pause auto-recovery).
// Fallback path (no SpeechRecognition): MediaRecorder → FormData → POST `${API_BASE}/stt`;
// while waiting show "Trascrizione…" in #voice-hint; on success append returned text.
// Permission denied (getUserMedia NotAllowedError / recognition onerror "not-allowed"):
```

show `#voice-error` with re-enable instructions + link to browser settings help; never a mute toast.

```js
// Network failure mid-dictation: keep partial committed text, show "Connessione persa, testo parziale salvato · Riprova".
```

- [ ] **Step 4: Auto-grow + counter**

```js
// On input/commit: freeText.style.height = "auto"; freeText.style.height = Math.min(freeText.scrollHeight, 7 * lineHeight) + "px";
// Counter element #free-count shows "4800/5000" only when length > 4500, else hidden.
```

- [ ] **Step 5: Verify**

  - `uv run pytest tests/test_contract.py tests/test_stt.py -q` → PASS (no payload/endpoint change).
  - `node --check` on extracted script → syntax OK.
  - Manual matrix: Chrome desktop (live tokens, hold, cancel-slide, lock, Esc, denied-permission),
    Safari (batch fallback, "Trascrizione…"), mobile Chrome Android (touch hold), 5000-char counter,
    Ctrl+Z undo after release appends.

- [ ] **Step 6: Commit**

```bash
git add docs/index.html
git commit -m "feat(frontend): WhatsApp-style voice composer with live tokens"
```

---

## Self-Review

**Spec coverage:** §3.1 → Tasks 1–3 ✓ (fields + intent prompt in T1; rule + rationale audit in T2;
  secondary-airport geo guidance in T3 Step 4; `_build_flight_combos` caps unchanged). §3.2 → Task 3 ✓.
§3.3 → Task 4 ✓.
§4 → Task 5 ✓ (structure, robustness, text part, C1 structural elimination). §5 → Task 7 ✓
(all states, engines, text handling). §6 → Task 6 ✓. §7 non-goals respected ✓.

**Precedence rule (from Task 2 execution):** with no airport codes anywhere, `no_airports` always wins
over `no_flights_needed`; `flight_rationale` is observable in `geo` only when airports resolve.
Task 5 does not consume it — audit only.

**Placeholder scan:** no TBD/TODO/"handle edge cases" without code; every step ships exact code.
**Type consistency:** `needs_flights: bool=True`, `flight_rationale: str=""`,
`JUNK_DOMAINS: frozenset[str]`, `_is_junk_link(str|None)->bool`, button targets via ≥14px
vertical padding + 16px text, mic element IDs (`voicebar`, `voice-wave`, `voice-timer`,
`voice-hint`, `voice-lock`, `voice-error`, `free-count`) used consistently.
