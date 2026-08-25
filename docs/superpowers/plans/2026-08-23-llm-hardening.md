# LLM Layer Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every sent email strictly grounded in researched data, season-aware when dates are absent, with sequential multi-query research and a variable-shape email that shows the research effort.

**Architecture:** The orchestrator's monolithic `_compose_package` is replaced by named stages (`_plan_period`, `_explore`, `_target`, `_execute_searches`, `_curate`, `_compose_email`) using the existing `LLMClient.extract()` mechanism only. A deterministic validation gate sits between composition and send. No new packages, no DB migration except dropping `flexible_dates`, no provider changes.

**Tech Stack:** Python 3.13, pydantic v2, pytest + pytest-asyncio (`asyncio_mode=auto`), fakeredis, SerpAPI (google_flights/google_maps/google_hotels), Resend.

**Spec:** `docs/superpowers/specs/2026-08-23-llm-hardening-design.md`

## Global Constraints

- Python >= 3.13 managed with `uv`; run everything as `uv run <cmd>`. Never create/use `.venv` inside the workspace.
- Tests: `uv run pytest` must be green before any commit proposal. No linter/typecheck exists; do not invent commands.
- Code, comments, docs in English. Email content stays Italian.
- **The OWNER executes every commit.** At each "Propose commit" step: print the proposed commit string, then STOP and wait for the owner to commit. Never run `git commit`.
- Branch: `fix/llm-hardening` off `dev`. PR into `dev` will be merged squash-style (single dot): commit strings below are proposals for that history.
- Do not change `LLMClient` protocol or any provider client (`src/services/apis/llm.py`). All new LLM usage goes through `extract(prompt, Model)`.
- Constants live module-level in `src/core/orchestrator.py`: `MAX_WINDOWS = 2`, `MAX_TARGET_QUERIES = 4`, `CORPUS_CAP = 8`.
- SerpAPI keys are never logged; `params` logged are the request dicts which never contain the key.

---

### Task 1: Deterministic validation functions

**Files:**
- Create: `src/core/validation.py`
- Test: `tests/test_validation.py`

**Interfaces:**
- Consumes: nothing (pure functions).
- Produces:
  - `AllowedResources(links: frozenset[str], names: frozenset[str])`
  - `build_allowed_resources(flights: list[dict], maps: list[dict], places: list[dict]) -> AllowedResources`
  - `validate_resources(resources: list[dict], allowed: AllowedResources) -> ValidationReport` where `ValidationReport(valid: list[dict], invalid: list[dict])`
  - `sanitize_windows(windows: list[dict], today: date) -> list[tuple[str, str]]` (used in Task 2)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_validation.py
from datetime import date

from src.core.validation import (
    AllowedResources,
    build_allowed_resources,
    sanitize_windows,
    validate_resources,
)

FLIGHTS = [{"name": "ANA", "price_eur": 320, "link": "https://f.example/ana"}]
MAPS = [{"name": "Senso-ji", "rating": 4.7, "link": "https://m.example/sensoji"}]
PLACES = [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://p.example/ryokan"}]


def test_build_allowed_collects_links_and_names():
    allowed = build_allowed_resources(FLIGHTS, MAPS, PLACES)
    assert isinstance(allowed, AllowedResources)
    assert "https://f.example/ana" in allowed.links
    assert "senso-ji" in allowed.names


def test_valid_resource_passes():
    allowed = build_allowed_resources(FLIGHTS, MAPS, PLACES)
    report = validate_resources(
        [{"name": "Senso-ji", "description": "", "price": "", "link": "https://m.example/sensoji"}],
        allowed,
    )
    assert len(report.valid) == 1 and report.invalid == []


def test_hallucinated_resource_is_invalid():
    allowed = build_allowed_resources(FLIGHTS, MAPS, PLACES)
    report = validate_resources(
        [{"name": "Museum of Modern Art", "description": "", "price": "", "link": "https://www.moma.org/"}],
        allowed,
    )
    assert report.valid == [] and len(report.invalid) == 1


def test_name_match_saves_missing_link():
    allowed = build_allowed_resources(FLIGHTS, MAPS, PLACES)
    report = validate_resources(
        [{"name": "Ryokan X", "description": "", "price": "95 EUR/notte", "link": ""}],
        allowed,
    )
    assert len(report.valid) == 1


def test_sanitize_windows_rejects_past_and_inverted_keeps_max2():
    today = date(2026, 8, 23)
    windows = [
        {"start": "2026-01-01", "end": "2026-02-01"},   # past -> dropped
        {"start": "2026-10-10", "end": "2026-09-01"},   # inverted -> dropped
        {"start": "2026-09-01", "end": "2026-09-30"},
        {"start": "2026-10-01", "end": "2026-10-31"},
        {"start": "2026-11-01", "end": "2026-11-30"},   # over cap -> dropped
    ]
    assert sanitize_windows(windows, today) == [
        ("2026-09-01", "2026-09-30"),
        ("2026-10-01", "2026-10-31"),
    ]


def test_sanitize_windows_fallback_when_nothing_usable():
    today = date(2026, 8, 23)
    assert sanitize_windows([], today) == [("2026-09-06", "2026-09-13")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_validation.py -v`
Expected: FAIL (`ModuleNotFoundError: src.core.validation`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/core/validation.py
"""Deterministic post-LLM checks: grounding of cited resources and date-window sanity."""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import NamedTuple


class AllowedResources(NamedTuple):
    links: frozenset[str]
    names: frozenset[str]


@dataclass
class ValidationReport:
    valid: list[dict]
    invalid: list[dict]


def build_allowed_resources(flights: list[dict], maps: list[dict], places: list[dict]) -> AllowedResources:
    categories = (flights, maps, places)
    links = frozenset(it["link"] for cat in categories for it in cat if it.get("link"))
    names = frozenset((it.get("name") or "").strip().lower() for cat in categories for it in cat if it.get("name"))
    return AllowedResources(links=links, names=names)


def validate_resources(resources: list[dict], allowed: AllowedResources) -> ValidationReport:
    valid, invalid = [], []
    for res in resources:
        link_ok = bool(res.get("link")) and res["link"] in allowed.links
        name_ok = (res.get("name") or "").strip().lower() in allowed.names
        (valid if (link_ok or name_ok) else invalid).append(res)
    return ValidationReport(valid=valid, invalid=invalid)


def sanitize_windows(windows: list[dict], today: date) -> list[tuple[str, str]]:
    usable: list[tuple[str, str]] = []
    for w in windows:
        try:
            start, end = date.fromisoformat(w["start"]), date.fromisoformat(w["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if start >= today and end >= start:
            usable.append((start.isoformat(), end.isoformat()))
    if not usable:
        fallback_start, fallback_end = today + timedelta(days=14), today + timedelta(days=21)
        return [(fallback_start.isoformat(), fallback_end.isoformat())]
    return usable[:2]
```

Note: name comparison is case-insensitive via lowercasing on both sides (test asserts `"Senso-ji"` matches lowered set).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_validation.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Propose commit**

```
feat(core): deterministic resource-validation and date-window sanitization helpers
```

---

### Task 2: New pipeline models + FakeLLM per-model dispatch

**Files:**
- Modify: `src/core/models.py` (append after `EmailContent`)
- Modify: `tests/fakes.py:17-36` (`FakeLLM`)
- Test: covered indirectly here; direct check in this task's step 1 via a tiny test file

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `DateWindow(start: str, end: str, rationale: str = "")`
  - `PeriodPlan(windows: list[DateWindow])`
  - `TargetQuery(query: str, based_on: str = "")`
  - `TargetQueries(queries: list[TargetQuery])`
  - `Curation(flight_indices: list[int], poi_indices: list[int], stay_indices: list[int], rationale: str = "")`
  - `FakeLLM(..., responses: dict[type, BaseModel] | None = None)` — new keyword; sensible defaults for the three new models so existing tests keep passing: empty `PeriodPlan`, empty `TargetQueries`, `Curation` selecting indices 0..2 per category.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fake_llm_dispatch.py
from src.core.models import Curation, PeriodPlan, TargetQueries, TripIntent
from tests.fakes import FakeLLM


async def test_fakellm_returns_model_specific_responses():
    llm = FakeLLM(response=TripIntent(destination="Tokyo"))
    plan = await llm.extract("p", PeriodPlan)
    tgt = await llm.extract("p", TargetQueries)
    cur = await llm.extract("p", Curation)
    assert plan == PeriodPlan(windows=[])
    assert tgt == TargetQueries(queries=[])
    assert cur.flight_indices == [0, 1, 2] and cur.poi_indices == [0, 1, 2] and cur.stay_indices == [0, 1, 2]


async def test_fakellm_explicit_responses_win():
    plan = PeriodPlan(windows=[{"start": "2026-09-01", "end": "2026-09-30", "rationale": "shoulder season"}])
    llm = FakeLLM(response=TripIntent(), responses={PeriodPlan: plan})
    assert await llm.extract("p", PeriodPlan) == plan
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fake_llm_dispatch.py -v`
Expected: FAIL (`ImportError: cannot import name 'PeriodPlan'`)

- [ ] **Step 3: Implement**

Append to `src/core/models.py`:

```python
class DateWindow(BaseModel):
    start: str = Field(description="Inizio finestra candidata, ISO YYYY-MM-DD")
    end: str = Field(description="Fine finestra candidata, ISO YYYY-MM-DD")
    rationale: str = Field(default="", description="Perché questa finestra è adatta al viaggio")


class PeriodPlan(BaseModel):
    windows: list[DateWindow] = Field(
        default_factory=list,
        description="Massimo 2 finestre temporali candidate, entrambe nel futuro",
    )


class TargetQuery(BaseModel):
    query: str = Field(description="Query di ricerca mirata, stessa lingua della destinazione")
    based_on: str = Field(default="", description="Anchor dall'esplorazione da cui deriva la query")


class TargetQueries(BaseModel):
    queries: list[TargetQuery] = Field(
        default_factory=list,
        description="Massimo 4 query mirate, ognuna derivata da un anchor dell'esplorazione",
    )


class Curation(BaseModel):
    flight_indices: list[int] = Field(default_factory=list, description="Indici dei voli selezionati")
    poi_indices: list[int] = Field(default_factory=list, description="Indici dei POI selezionati")
    stay_indices: list[int] = Field(default_factory=list, description="Indici degli alloggi selezionati")
    rationale: str = Field(default="", description="Breve motivazione delle scelte, in italiano")
```

Replace `tests/fakes.py:17-36` (`FakeLLM`) with:

```python
class FakeLLM(LLMClient):
    """Deterministic in-memory LLM with configurable per-model responses."""

    def __init__(self, response=None, email_response=None, error: Exception | None = None,
                 responses: dict[type, BaseModel] | None = None):
        self._response = response
        self._email_response = email_response or response
        self._error = error
        self._responses = responses or {}
        self.calls: list[tuple[str, type]] = []

    async def extract[T: BaseModel](self, prompt: str, model: type[T]) -> T:
        from src.core.models import Curation, EmailContent, PeriodPlan, TargetQueries, TripIntent

        self.calls.append((prompt, model))
        if self._error is not None:
            raise self._error
        if model in self._responses:
            return self._responses[model]
        if model is EmailContent:
            return self._email_response
        if model is TripIntent:
            return self._response
        if model is PeriodPlan:
            return PeriodPlan(windows=[])
        if model is TargetQueries:
            return TargetQueries(queries=[])
        if model is Curation:
            return Curation(flight_indices=[0, 1, 2], poi_indices=[0, 1, 2], stay_indices=[0, 1, 2])
        return self._response
```

(`BaseModel` import already exists at top of `tests/fakes.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fake_llm_dispatch.py tests/test_orchestrator.py -v`
Expected: PASS (new tests pass; existing orchestrator tests unaffected because the new models are not yet called by the orchestrator)

- [ ] **Step 5: Propose commit**

```
feat(core): add PeriodPlan/TargetQueries/Curation schemas and per-model FakeLLM dispatch
```

---

### Task 3: Period planning + multi-window flight probing

**Files:**
- Modify: `src/core/orchestrator.py` (add `_plan_period`; rework search fan-out inside what is still `_compose_package` until Task 5 renames it)
- Modify: `src/core/prompts/__init__.py` (add `build_period_prompt`)
- Test: `tests/test_orchestrator.py` (extend)

**Interfaces:**
- Consumes: `PeriodPlan` (Task 2), `sanitize_windows` (Task 1), `FakeLLM(responses={PeriodPlan: ...})`.
- Produces: `TripOrchestrator._plan_period(trip) -> list[tuple[str, str]]` (1–2 `(start,end)` ISO pairs). Flight probing picks the cheapest across windows; stays receive the winning window.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_orchestrator.py`:

```python
from src.core.models import PeriodPlan


async def test_no_dates_triggers_period_plan_and_multi_window_flight_probe(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip(start_date=None, end_date=None))
    llm = FakeLLM(
        response=INTENT,
        email_response=EMAIL,
        responses={PeriodPlan: PeriodPlan(windows=[
            {"start": "2026-09-01", "end": "2026-09-15", "rationale": "mild"},
            {"start": "2026-10-01", "end": "2026-10-15", "rationale": "cheaper"},
        ])},
    )

    seen_outbound_dates = []

    async def fake_flights(departure, destination, start_date, end_date, **kwargs):
        seen_outbound_dates.append(start_date)
        price = 400 if start_date == "2026-09-01" else 300
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": start_date,
                 "price_eur": price, "link": f"https://example.com/{start_date}"}]

    stay_windows = []

    async def fake_places(*args, **kwargs):
        stay_windows.append(kwargs.get("check_in_date"))
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    async def fake_maps(*args, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    email = FakeEmailSender()
    db = FakeDatabase()
    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=email,
                                    database=db, trip_id=trip.id)
    await _run(orchestrator)

    assert sorted(seen_outbound_dates) == ["2026-09-01", "2026-10-01"]  # both windows probed
    assert stay_windows[-1] == "2026-10-01"  # stays aligned to cheapest window
    assert email.sent and db.saved  # trip completes


async def test_unusable_period_plan_falls_back(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip(start_date=None, end_date=None))
    llm = FakeLLM(response=INTENT, email_response=EMAIL)  # default PeriodPlan(windows=[])

    seen = []

    async def fake_flights(*args, **kwargs):
        seen.append(kwargs.get("outbound_date") or args[2])
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "x",
                 "price_eur": 300, "link": "https://example.com/f"}]

    async def fake_maps(*args, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(*args, **kwargs):
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=FakeEmailSender(),
                                    database=FakeDatabase(), trip_id=trip.id)
    await _run(orchestrator)

    assert len(seen) == 1  # exactly the fallback window
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_orchestrator.py -k "period_plan or falls_back" -v`
Expected: FAIL (both probes not happening / attribute missing)

- [ ] **Step 3: Implement**

In `src/core/prompts/__init__.py` add:

```python
def build_period_prompt(trip: TripResponse, today_iso: str) -> str:
    return f"""The traveler gave no dates. Propose the best travel windows for this trip.

    Today is {today_iso}.
    Destination: {trip.destination or "not specified"}
    Interests: {', '.join(travel_interests(trip)) or 'not specified'}

    Consider the best season for the destination (climate, crowding, prices) and the traveler's interests.
    Return at most 2 windows in the future, each with a short Italian rationale.
    """
```

(Note: `travel_interests` does not exist — use `intent` instead; see below.) Correct version — the orchestrator has the intent at hand, so signature is `build_period_prompt(trip, intent, today_iso)` and the interests line is `Interests: {', '.join(intent.interests) or 'not specified'}`. Style signals: append `Style: {', '.join(intent.style) or 'not specified'}`.

In `src/core/orchestrator.py`:

```python
from datetime import date, datetime, timezone  # extend existing datetime import
from src.core.models import EmailContent, PeriodPlan, TripIntent
from src.core.prompts import build_email_prompt, build_intent_prompt, build_period_prompt
from src.core.validation import build_allowed_resources, sanitize_windows, validate_resources
```

Constants near the top:

```python
MAX_WINDOWS = 2
```

New method on `TripOrchestrator`:

```python
async def _plan_period(self, trip: TripResponse, intent: TripIntent) -> list[tuple[str, str]]:
    if trip.start_date and trip.end_date:
        return [(trip.start_date, trip.end_date)]
    if trip.start_date:
        return [(trip.start_date, trip.start_date)]
    prompt = build_period_prompt(trip, intent, date.today().isoformat())
    plan = await self._llm.extract(prompt, PeriodPlan)
    windows = sanitize_windows([w.model_dump() for w in plan.windows], date.today())
    logger.info("period plan: %d usable window(s)", len(windows))
    return windows[:MAX_WINDOWS]
```

Rework the search block in `_compose_package` (replace the single `flights.search(...)` entry of the `asyncio.gather`):

```python
windows = await self._plan_period(trip, intent)

async def _probe_window(window: tuple[str, str]) -> list[dict]:
    return await flights.search(
        departure_code, destination_code, window[0], window[1],
        timeout=self._serpapi_timeout, api_key=self._serpapi_api_key,
    )

flight_lists = await asyncio.gather(*(_probe_window(w) for w in windows))
flight_candidates = [f for lst in flight_lists for f in lst]
best_flight = min(flight_candidates, key=lambda f: f.get("price_eur") or float("inf"), default=None)
winning_window = next((w for w in windows if best_flight and best_flight.get("departure_date", "").startswith(w[0])), windows[0])
flights_list = [best_flight] if best_flight else []
```

Then run maps and places (places gets `check_in_date=winning_window[0], check_out_date=winning_window[1]` when the trip had no explicit end date, otherwise its current arguments). Keep the existing empty-corpus guard (`NoResourcesError`) unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: PASS (new tests + all existing ones; note `test_all_searches_empty_aborts_without_email` still passes because with default `PeriodPlan([])` there is exactly one fallback probe)

- [ ] **Step 5: Propose commit**

```
feat(core): season-aware period planning with multi-window flight probing and cheapest-window selection
```

---

### Task 4: Tools generalization (maps multi-query, places link filter)

**Files:**
- Modify: `src/services/tools/maps.py`
- Modify: `src/services/tools/places.py`
- Modify: `src/services/tools/__init__.py` (add `dedupe_cap`)
- Test: `tests/test_tools.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `maps.research(query: str, timeout, api_key) -> list[dict]` — ONE query, positional, replaces `(destination, interests)`; caller owns query composition.
  - `places.search(check_in_date=None, check_out_date=None, timeout, api_key, *, destination: str) -> list[dict]` — drops `interests/style` params; skips properties without `link`; caps at 8 via `dedupe_cap`.
  - `dedupe_cap(items: list[dict], cap: int = 8) -> list[dict]` — dedup by `(name, link)`, preserve order, cap.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tools.py
import pytest

from src.services.tools import dedupe_cap
from src.services.tools.maps import research as maps_research
from src.services.tools.places import search as places_search


def test_dedupe_cap_preserves_order_and_caps():
    items = [{"name": "a", "link": "1"}, {"name": "b", "link": "2"}, {"name": "a", "link": "1"}, {"name": "c", "link": "3"}]
    assert dedupe_cap(items, cap=2) == [{"name": "a", "link": "1"}, {"name": "b", "link": "2"}]


async def test_maps_research_issues_single_query(monkeypatch):
    captured = {}

    async def fake_serpapi(params, timeout=60.0, api_key=None):
        captured.update(params)
        return {"local_results": [{"title": "Shibuya", "type": "District", "rating": 4.5}]}

    monkeypatch.setattr("src.services.tools.maps.serpapi_search", fake_serpapi)
    out = await maps_research("quartieri e luoghi chiave a Tokyo")
    assert captured["q"] == "quartieri e luoghi chiave a Tokyo"
    assert out == [{"name": "Shibuya", "type": "District", "rating": 4.5, "reviews_count": None, "address": None, "description": None, "link": None}]


async def test_places_search_drops_linkless_and_caps(monkeypatch):
    async def fake_serpapi(params, timeout=60.0, api_key=None):
        return {"properties": [
            {"name": "NoLink", "type": "hotel", "rate_per_night": {"extracted_lowest": 50}, "total_rate": {}, "essential_info": None, "link": None},
            {"name": "Ok", "type": "hotel", "rate_per_night": {"extracted_lowest": 90}, "total_rate": {}, "essential_info": None, "link": "https://h.example/ok"},
        ]}

    monkeypatch.setattr("src.services.tools.places.serpapi_search", fake_serpapi)
    out = await places_search(destination="Tokyo", check_in_date="2026-09-01", check_out_date="2026-09-10")
    assert [o["name"] for o in out] == ["Ok"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools.py -v`
Expected: FAIL (`ImportError: dedupe_cap`; `maps_research` signature mismatch)

- [ ] **Step 3: Implement**

`src/services/tools/__init__.py` — add:

```python
def dedupe_cap(items: list[dict], cap: int = 8) -> list[dict]:
    seen: set[tuple] = set()
    out: list[dict] = []
    for it in items:
        key = (it.get("name"), it.get("link"))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out[:cap]
```

`src/services/tools/maps.py` — replace `research`:

```python
async def research(query: str, timeout: float = 60.0, api_key: str | None = None) -> list[dict]:
    """Searches points of interest on Google Maps via SerpAPI for ONE query."""
    if not query:
        return []
    data = await serpapi_search(
        {"engine": "google_maps", "q": query, "type": "search", "hl": "it"},
        timeout=timeout,
        api_key=api_key,
    )
    return [_normalize(p) for p in data.get("local_results", [])]
```

`src/services/tools/places.py` — replace `search` (drop `interests/style`, drop `_default_dates` usage stays, skip link-less, cap):

```python
async def search(
    *,
    destination: Optional[str],
    check_in_date: Optional[str] = None,
    check_out_date: Optional[str] = None,
    timeout: float = 60.0,
    api_key: str | None = None,
) -> list[dict]:
    """Searches accommodations on Google Hotels via SerpAPI."""
    if not destination:
        return []

    query = f"hotels in {destination}"
    check_in, check_out = check_in_date, check_out_date
    if not check_in or not check_out:
        check_in, check_out = _default_dates()
    data = await serpapi_search(
        {
            "engine": "google_hotels",
            "q": query,
            "check_in_date": check_in,
            "check_out_date": check_out,
            "hl": "it",
            "gl": "it",
            "currency": "EUR",
        },
        timeout=timeout,
        api_key=api_key,
    )
    properties = [_normalize(p) for p in data.get("properties", [])]
    linked = [p for p in properties if p.get("link")]
    return dedupe_cap(linked, cap=8)
```

(add `from src.services.tools import dedupe_cap` — careful: circular import; instead define `dedupe_cap` in `src/services/tools/__init__.py` and have places import it lazily or move normalization-time filtering inline; simplest: put `dedupe_cap` in a new tiny module `src/services/tools/_util.py` and import from both `__init__.py` and `places.py`.)

Update the two call sites in `tests/test_orchestrator.py` monkeypatches if signatures changed (they patch the functions wholesale, so only keyword-name mismatches matter: existing fakes accept `*args, **kwargs` — safe).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools.py tests/test_orchestrator.py -v`
Expected: PASS (orchestrator tests updated in Task 5 for new call shapes; if any fail here due to `maps.research(destination, interests)` positional call inside `_compose_package`, adapt the orchestrator call minimally: pass a single composed query string)

- [ ] **Step 5: Propose commit**

```
refactor(tools): single-query maps API, link-filtered capped stays, shared dedupe_cap util
```

---

### Task 5: Explore → target → curate stages + hardened prompts + tool log (F2/F4/F5)

**Files:**
- Modify: `src/core/orchestrator.py` (rename/split `_compose_package` into `_explore`, `_target`, `_execute_searches`, `_curate`, `_compose_email`; delete `_compose_package`)
- Modify: `src/core/prompts/__init__.py` (`build_target_prompt`, `build_curation_prompt`, rewrite `build_email_prompt`, harden `build_intent_prompt`)
- Modify: `src/core/prompts/system_prompt.md`
- Test: `tests/test_orchestrator.py` (update + extend)

**Interfaces:**
- Consumes: `TargetQueries`, `Curation` (Task 2), `dedupe_cap` (Task 4), `maps.research(query)` (Task 4).
- Produces:
  - `TripOrchestrator._explore(destination) -> list[dict]`
  - `TripOrchestrator._target(trip, intent, anchors) -> list[str]`
  - `TripOrchestrator._execute_searches(trip, intent, targeted_queries, windows) -> dict` with keys `corpus` (`{"flights","maps","places"}` capped at 8/category), `tool_calls` (list of `{engine, params, result_count}`), `sources` (list of source-search URLs), `winning_window`
  - `TripOrchestrator._curate(trip, intent, corpus) -> dict` `{"flights","maps","places"}` subsets
  - Package saved to history gains `corpus`, `curated`, `tool_calls` keys alongside `intent`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_orchestrator.py`:

```python
from src.core.models import Curation, TargetQueries


async def test_stages_run_in_order_and_package_records_tool_calls(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT, email_response=EMAIL)
    order = []

    async def fake_flights(*args, **kwargs):
        order.append("flights")
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01",
                 "price_eur": 320, "link": "https://example.com/flight",
                 "_meta": {"google_flights_url": "https://gf.example"}}]

    async def fake_maps(query, **kwargs):
        order.append(f"maps:{query}")
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        order.append("places")
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    email = FakeEmailSender()
    db = FakeDatabase()
    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=email,
                                    database=db, trip_id=trip.id)
    await _run(orchestrator)

    assert order[0].startswith("maps:")          # explore first
    assert "places" in order and "flights" in order
    assert len(db.saved) == 1
    package = db.saved[0]["package"]
    assert package["tool_calls"], "every serpapi call must be logged"
    assert all(set(tc) == {"engine", "params", "result_count"} for tc in package["tool_calls"])
    assert "corpus" in package and "curated" in package


async def test_curation_indices_out_of_range_are_dropped(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(
        response=INTENT,
        email_response=EMAIL,
        responses={Curation: Curation(flight_indices=[99], poi_indices=[0], stay_indices=[0])},
    )

    async def fake_flights(*args, **kwargs):
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01",
                 "price_eur": 320, "link": "https://example.com/flight"}]

    async def fake_maps(*args, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    db = FakeDatabase()
    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=FakeEmailSender(),
                                    database=db, trip_id=trip.id)
    await _run(orchestrator)

    assert db.saved[0]["package"]["curated"]["flights"] == []      # index 99 dropped
    assert len(db.saved[0]["package"]["curated"]["maps"]) == 1
```

Update existing test fakes: `fake_maps` signatures become `(query, **kwargs)`; `fake_places` becomes `(**kwargs)` with `destination=` keyword. Update the four existing tests accordingly.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_orchestrator.py -k "stages_run or out_of_range" -v`
Expected: FAIL (`package` has no `tool_calls` key)

- [ ] **Step 3: Implement**

`src/core/prompts/__init__.py`:

```python
def build_target_prompt(trip: TripResponse, intent: TripIntent, anchors_block: str) -> str:
    return f"""You plan targeted research for this trip. You are given exploration anchors
    (areas, landmark types) discovered for the destination.

    TRIP CONTEXT (verbatim user brief below — do NOT assume preferences not present here):
    Destination: {trip.destination or "not specified"}
    Interests: {', '.join(intent.interests) or 'not specified'}
    Style: {', '.join(intent.style) or 'not specified'}
    Pace: {intent.pace or 'not specified'}

    EXPLORATION ANCHORS:
    {anchors_block}

    USER FREE TEXT (verbatim):
    "{trip.free_text}"

    Propose at most 4 targeted Google-Maps search queries (same language as the destination)
    that dig INTO the anchors along the brief's interests and style — e.g. specific
    neighborhoods, niche venues, quiet alternatives. Each query must derive from an anchor.
    """


def build_curation_prompt(trip: TripResponse, intent: TripIntent, corpus_blocks: str) -> str:
    return f"""Select the best resources for this traveler from the numbered corpus below.

    TRIP CONTEXT:
    Interests: {', '.join(intent.interests) or 'not specified'}
    Style: {', '.join(intent.style) or 'not specified'}
    Pace: {intent.pace or 'not specified'}

    CORPUS (numbered; reference ONLY these indices):
    {corpus_blocks}

    Rules: pick by merit for THIS brief — quality and fit, never filler. Zero items in a
    category is a valid choice when nothing fits. Return indices only, plus a short
    Italian rationale.
    """
```

Rewrite `build_email_prompt` (hardened, ID-referenced, quota-free):

```python
def build_email_prompt(
    intent: TripIntent,
    flights_block: str,
    maps_block: str,
    places_block: str,
    trip: TripResponse | None = None,
) -> str:
    return f"""Write the trip email for this traveler.

    TRIP CONTEXT (only these preferences exist — never invent others):
    Interests: {', '.join(intent.interests) or 'not specified'}
    Style sought: {', '.join(intent.style) or 'not specified'}
    Pace: {intent.pace or 'not specified'}
    Travelers: {trip.travelers_composition if trip else 'not specified'}
    Budget: {trip.budget_amount if trip else 'not specified'}
    Travel mode: {trip.travel_mode if trip else 'not specified'}
    Stay preference: {trip.stay_preference if trip else 'not specified'}

    USER FREE TEXT (verbatim):
    "{trip.free_text if trip else ''}"

    RESOURCES AVAILABLE (IDs in brackets; cite ONLY these):
    Flights:
    {flights_block}

    Points of interest:
    {maps_block}

    Accommodation:
    {places_block}
    """
```

Harden `build_intent_prompt`: append the line `- Copy preferences ONLY from the fields and free text above; leave everything else null.`

`src/core/prompts/system_prompt.md` — replace rule 8-line block with:

```markdown
Always valid ground rules:
- Output in ITALIAN, PLAIN TEXT: no markdown, asterisks, dashes or hashtags.
- Use ONLY the resources provided, citing their bracket IDs; if a category has no worthwhile item, omit it entirely — never fill space.
- State ONLY preferences present in the context or verbatim free text. If something is "not specified", it does not exist for you.
- Max 2-3 sentences in total between opening and understanding. The signature is added by the system.
- Never present yourself as an AI to the traveler.
```

(Removes the forced "THREE items" rule.)

`src/core/orchestrator.py` — replace `_compose_package` with:

```python
async def _explore(self, destination: str) -> list[dict]:
    query = f"quartieri e luoghi chiave in {destination}"
    return await maps.research(query, timeout=self._serpapi_timeout, api_key=self._serpapi_api_key)

async def _target(self, trip: TripResponse, intent: TripIntent, anchors: list[dict]) -> list[str]:
    if not anchors:
        return []
    anchors_block = "\n".join(
        f"- {a.get('name')} ({a.get('type')}) {a.get('address') or ''}".strip() for a in anchors[:8]
    )
    plan = await self._llm.extract(build_target_prompt(trip, intent, anchors_block), TargetQueries)
    return [q.query for q in plan.queries][:MAX_TARGET_QUERIES]

async def _log_call(self, tool_calls: list[dict], engine: str, params: dict, results: list[dict]) -> None:
    tool_calls.append({"engine": engine, "params": params, "result_count": len(results)})
    logger.info("%s: %d results (%s)", engine, len(results), params.get("q") or params.get("departure_id"))

async def _execute_searches(self, trip: TripResponse, intent: TripIntent,
                            targeted_queries: list[str], windows: list[tuple[str, str]]) -> dict:
    destination = intent.destination or trip.destination
    departure_code = intent.departure_airport_code or trip.departure_location
    destination_code = intent.destination_airport_code or destination
    tool_calls: list[dict] = []
    errors: list[Exception] = []

    async def guarded(coro, engine: str, params: dict):
        try:
            res = await coro
        except Exception as exc:  # noqa: BLE001 — mirrored from previous behavior
            errors.append(exc)
            logger.warning("%s: error %s: %s", engine, type(exc).__name__, exc)
            return []
        await self._log_call(tool_calls, engine, params, res)
        return res

    maps_results = await asyncio.gather(*(
        guarded(maps.research(q, timeout=self._serpapi_timeout, api_key=self._serpapi_api_key),
                "google_maps", {"q": q})
        for q in targeted_queries
    ))

    async def probe(window: tuple[str, str]):
        params = {"departure_id": departure_code, "arrival_id": destination_code,
                  "outbound_date": window[0], "return_date": window[1]}
        res = await guarded(flights.search(departure_code, destination_code, window[0], window[1],
                                           timeout=self._serpapi_timeout, api_key=self._serpapi_api_key),
                            "google_flights", params)
        return window, res

    probed = await asyncio.gather(*(probe(w) for w in windows))
    candidates = [(w, f) for w, fs in probed for f in fs]
    sources = []
    for _, f in candidates:
        url = f.get("_meta", {}).get("google_flights_url") if isinstance(f.get("_meta"), dict) else None
        if url:
            sources.append(url)

    best = min(candidates, key=lambda wf: wf[1].get("price_eur") or float("inf"), default=None)
    flights_list = ([{**best[1]}] if best else [])
    winning_window = best[0] if best else windows[0]

    check_in = trip.start_date or winning_window[0]
    check_out = trip.end_date or winning_window[1]
    stays = await guarded(
        places.search(destination=destination, check_in_date=check_in, check_out_date=check_out,
                      timeout=self._serpapi_timeout, api_key=self._serpapi_api_key),
        "google_hotels", {"q": f"hotels in {destination}", "check_in_date": check_in, "check_out_date": check_out},
    )

    corpus = {
        "flights": [{k: v for k, v in f.items() if k != "_meta"} for f in flights_list],
        "maps": dedupe_cap([i for lst in maps_results for i in lst], cap=CORPUS_CAP),
        "places": stays,
    }
    if not any(corpus.values()):
        if errors:
            raise NoResourcesError("No resources retrieved from SerpAPI (all searches failed): email not sent")
        raise NoResourcesError("No resources retrieved from SerpAPI (all searches empty): email not sent")
    return {"corpus": corpus, "tool_calls": tool_calls, "sources": sources, "winning_window": winning_window}

def _render_numbered(items: list[dict], prefix: str) -> str:
    if not items:
        return "none available"
    return "\n".join(f"[{prefix}{i}] {it.get('name')} — {it.get('link')}" for i, it in enumerate(items, 1))

async def _curate(self, trip: TripResponse, intent: TripIntent, corpus: dict) -> dict:
    blocks = (
        f"Flights:\n{self._render_numbered(corpus['flights'], 'F')}\n\n"
        f"Points of interest:\n{self._render_numbered(corpus['maps'], 'M')}\n\n"
        f"Accommodation:\n{self._render_numbered(corpus['places'], 'P')}"
    )
    cur = await self._llm.extract(build_curation_prompt(trip, intent, blocks), Curation)

    def pick(indices: list[int], items: list[dict]) -> list[dict]:
        out = []
        for idx in indices:
            if 1 <= idx <= len(items):
                out.append(items[idx - 1])
            else:
                logger.warning("curation index %d out of range (1..%d) — dropped", idx, len(items))
        return out[:3]

    curated = {
        "flights": pick(cur.flight_indices, corpus["flights"]),
        "maps": pick(cur.poi_indices, corpus["maps"]),
        "places": pick(cur.stay_indices, corpus["places"]),
    }
    if not any(curated.values()):
        # merit fallback: keep corpus top items rather than aborting a researched trip
        curated = {k: v[:3] for k, v in corpus.items()}
    return curated
```

`_compose_email` becomes the former tail of `_compose_package`:

```python
async def _compose_email(self, trip: TripResponse, intent: TripIntent, research: dict) -> tuple[dict, str, str, dict]:
    corpus, curated = research["corpus"], research["curated"]
    allowed = build_allowed_resources(curated["flights"], curated["maps"], curated["places"])

    prompt = build_email_prompt(intent,
                                self._render_flights(curated["flights"], numbered=True),
                                self._render_maps(curated["maps"], numbered=True),
                                self._render_places(curated["places"], numbered=True),
                                trip)
    content = (await self._llm.extract(prompt, EmailContent)).model_dump()

    report = validate_resources(content["resources"], allowed)
    if report.invalid:
        logger.warning("invalid resources dropped: %s", [r.get("name") for r in report.invalid])
        content["resources"] = report.valid
        if not content["resources"]:
            retry_prompt = prompt + "\n\nIMPORTANT: your previous answer cited resources not in the list and was rejected. Use ONLY the listed resources."
            content = (await self._llm.extract(retry_prompt, EmailContent)).model_dump()
            report = validate_resources(content["resources"], allowed)
            content["resources"] = report.valid
            if not content["resources"]:
                raise NoResourcesError("email composition could not ground any real resource")

    content["honest_note"] = HONEST_NOTE
    content["cta"] = CTA
    content["appendix"] = self._build_appendix(research)
    body_text = self._compose_body_text(content)
    body_html = build_html_email(content)
    package = {
        "intent": intent.model_dump(),
        "corpus": corpus,
        "curated": curated,
        "tool_calls": research["tool_calls"],
    }
    return content, body_text, body_html, package
```

`run()` rewiring (inside the try, replacing the `compose_package` timed block):

```python
intent = await self._extract_intent(trip)

async with self._timed("research"):
    windows = await self._plan_period(trip, intent)
    anchors = await self._explore(intent.destination or trip.destination)
    targeted = await self._target(trip, intent, anchors)
    research = await self._execute_searches(trip, intent, targeted, windows)

async with self._timed("curate+compose"):
    curated = await self._curate(trip, intent, research["corpus"])
    research["curated"] = curated
    email_content, body_text, body_html, package = await self._compose_email(trip, intent, research)
```

Adapt `_render_flights/_render_maps/_render_places` to accept `numbered: bool = False` and prefix `[F1]`/`[M1]`/`[P1]`. Add `_build_appendix(research) -> dict` producing `{"groups": [("Voli", [{"name","link"}...]), ("Dove stare", [...]), ("Cosa fare", [...])], "source_links": research["sources"]}` from `research["corpus"]`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: PASS (all, including updated legacy tests)

- [ ] **Step 5: Propose commit**

```
feat(core): staged research pipeline (explore->target->execute->curate) with grounded email composition, tool-call logging and corpus persistence
```

---

### Task 6: Variable-shape email rendering + sources appendix (F6)

**Files:**
- Modify: `src/services/apis/email.py` (`build_html_email`, card grouping, appendix)
- Modify: `src/services/templates/email.html` (generic heading, `$resource_groups`, `$appendix` placeholders)
- Modify: `src/core/orchestrator.py` (`_compose_body_text` groups + plain-text fonti)
- Test: `tests/test_email_rendering.py` (new)

**Interfaces:**
- Consumes: `content["appendix"] = {"groups": [(label, [{"name","link"}...])], "source_links": [str]}` produced in Task 5.
- Produces: `build_html_email(content: dict) -> str` unchanged signature; template renders only non-empty groups; `<details class="appendix">` block.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_email_rendering.py
from src.services.apis.email import build_html_email

CONTENT = {
    "opening": "Apertura.",
    "understanding": "Comprensione.",
    "cta": "CTA.",
    "honest_note": "Nota.",
    "resources": [
        {"name": "Volino", "description": "", "price": "300 EUR", "link": "https://f.example"},
        {"name": "Posto", "description": "", "price": "", "link": "https://m.example"},
    ],
    "appendix": {
        "groups": [
            ("Voli", [{"name": "Altro volo", "link": "https://f.example/2"}]),
            ("Dove stare", []),
            ("Cosa fare", [{"name": "POI due", "link": "https://m.example/2"}]),
        ],
        "source_links": ["https://gf.example"],
    },
}


def test_empty_group_not_rendered_but_nonempty_is():
    html = build_html_email(CONTENT)
    assert "Voli" in html and "Cosa fare" in html
    assert "Dove stare" not in html.split("<details")[0]  # absent among curated cards


def test_appendix_details_present_with_all_links():
    html = build_html_email(CONTENT)
    assert "<details" in html and "</details>" in html
    assert "https://f.example/2" in html and "https://m.example/2" in html
    assert "https://gf.example" in html


def test_no_quota_heading():
    html = build_html_email(CONTENT)
    assert "tre punti" not in html.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_email_rendering.py -v`
Expected: FAIL (no `<details>`, "tre punti" still in template)

- [ ] **Step 3: Implement**

`email.html` changes:
- Heading div text `Ecco tre punti di partenza concreti` → `Ecco i punti di partenza`.
- Replace `<tr>` block containing `$resource_cards` with `<td>$resource_groups</td>`.
- Insert after the resources row, before CTA row:

```html
<!-- Fonti esplorate -->
<tr>
  <td class="gutter" style="padding:20px 36px 0;">
    $appendix
  </td>
</tr>
```

`email.py` changes:

```python
_GROUP_HEADINGS = {"flights": "Voli", "places": "Dove stare", "maps": "Cosa fare"}

def _render_group(label: str, items: list[dict]) -> str:
    if not items:
        return ""
    head = f'<div style="font-family:\'IBM Plex Sans\',Arial,sans-serif;font-size:12px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#4E6071;margin:16px 0 8px;">{_e(label)}</div>'
    return head + "\n".join(_render_card(item) for item in items)

def _render_appendix(appendix: dict) -> str:
    rows = []
    for label, items in appendix.get("groups", []):
        if not items:
            continue
        lis = "\n".join(
            f'<li style="margin:2px 0;"><a href="{_e(i["link"])}" target="_blank" style="color:#4E6071;">{_e(i["name"])}</a></li>'
            for i in items if i.get("link")
        )
        rows.append(f'<div style="font-size:12px;color:#4E6071;margin-top:6px;">{_e(label)}</div><ul style="margin:4px 0 0;padding-left:18px;">{lis}</ul>')
    src = "".join(f' <a href="{_e(u)}" target="_blank" style="color:#7A8895;">ricerca</a>' for u in appendix.get("source_links", []) if u)
    if not rows and not src:
        return ""
    inner = "".join(rows) + (f'<div style="font-size:11px;color:#7A8895;margin-top:10px;">Ricerche effettuate:{src}</div>' if src else "")
    return (
        '<details style="margin-top:8px;"><summary style="cursor:pointer;font-family:\'IBM Plex Sans\',Arial,sans-serif;'
        'font-size:12px;font-weight:600;color:#4E6071;">Tutto quello che abbiamo esplorato</summary>'
        f'<div style="font-family:\'IBM Plex Sans\',Arial,sans-serif;">{inner}</div></details>'
    )
```

`build_html_email` groups `content["resources"]` back into categories via link membership against `content["sections_map"]` (produced by orchestrator: `{"flights": [links...], "places": [...], "maps": [...]}` from curated sets) — add that key in `_compose_email` right after validation:

```python
content["sections_map"] = {
    "flights": [r["link"] for r in curated["flights"] if r.get("link")],
    "places": [r["link"] for r in curated["places"] if r.get("link")],
    "maps": [r["link"] for r in curated["maps"] if r.get("link")],
}
```

and in `email.py`:

```python
def _grouped_cards(content: dict) -> str:
    smap = content.get("sections_map", {})
    used: set[str] = set()
    out = []
    for kind, label in _GROUP_HEADINGS.items():
        allow = set(smap.get(kind, []))
        items = [r for r in content.get("resources", []) if r.get("link") in allow and r["link"] not in used]
        for r in items:
            used.add(r["link"])
        out.append(_render_group(label, items))
    leftovers = [r for r in content.get("resources", []) if r.get("link") not in used]
    if leftovers:
        out.append("\n".join(_render_card(r) for r in leftovers))  # unmatched singles render flat
    return "\n".join(o for o in out if o)
```

Substitute `safe_substitute(..., resource_groups=_grouped_cards(content), appendix=_render_appendix(content.get("appendix", {})))`; remove `resource_cards` placeholder use.

`_compose_body_text` in orchestrator: heading line becomes `"Ecco i punti di partenza:"`; after resources append:

```python
lines.append("")
lines.append("Fonti esplorate:")
for label, items in content["appendix"]["groups"]:
    named = [i for i in items if i.get("link")]
    if named:
        lines.append(f"{label}: " + "; ".join(f"{i['name']} {i['link']}" for i in named))
for url in content["appendix"].get("source_links", []):
    lines.append(f"Ricerca voli: {url}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_email_rendering.py tests/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 5: Propose commit**

```
feat(email): variable-shape sections, expandable sources appendix with full corpus links
```

---

### Task 7: Remove `flexible_dates` end-to-end + ADR (F7)

**Files:**
- Modify: `src/core/schemas.py:21` — delete the field
- Modify: `src/services/trip_store.py:32,92` — remove write/read
- Modify: `src/infrastructure/database.py:18,34,52` — remove parameter and column references
- Modify: `src/core/orchestrator.py:126` — remove kwarg from `save_trip_history` call
- Modify: `schema.sql:7` — remove column line; append migration:
  ```sql
  -- Upgrade existing databases: flexible_dates removed (dates absent => system chooses window).
  ALTER TABLE trip_history DROP COLUMN IF EXISTS flexible_dates;
  ```
- Modify: `docs/index.html:747` — remove the `<label class="flex-check">…</label>` line; `docs/index.html:1210` — remove `flexible_dates:` payload line
- Modify: `README.md` (~lines 71,88) and `AGENTS.md` curl examples — remove `"flexible_dates": …,` lines
- Create: `docs/adr/007-period-planning-and-flexible-dates-removal.md` (Status: Accepted; Context: dead flag + new period-planning semantics; Decision: dates present = constraint, absent = LLM-proposed windows; Consequences: breaking contract, coordinated deploy)
- Modify: `tests/fakes.py:84`, `tests/test_trip_store.py:18`, `tests/test_contract.py:55` — remove usages

**Interfaces:**
- Consumes: nothing.
- Produces: `TripCreateRequest` without `flexible_dates`; DB without the column; frontend form without the checkbox.

- [ ] **Step 1: Write the failing test (contract-level)**

In `tests/test_contract.py`, change the posted payload (remove `"flexible_dates"` key) and add:

```python
async def test_flexible_dates_field_rejected(client):
    resp = await client.post("/api/v1/trips", json={...minimal valid payload..., "flexible_dates": True})
    assert resp.status_code == 422
```

(follow the existing fixture/payload style in that file; the minimal-valid-payload placeholder must be replaced with the file's actual base payload minus `flexible_dates`)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_contract.py -v`
Expected: FAIL (field currently accepted)

- [ ] **Step 3: Implement all removals listed in Files**

Pydantic v2 default ignores extra input fields, so `TripResponse` parsing of old Redis records containing `flexible_dates` keeps working — no store migration needed beyond SQL.

- [ ] **Step 4: Run full suite**

Run: `uv run pytest`
Expected: PASS (all files updated consistently)

- [ ] **Step 5: Apply schema change on VM (manual, per repo convention)**

```bash
psql "$NOSTOS_DATABASE_URL" -c "ALTER TABLE trip_history DROP COLUMN IF EXISTS flexible_dates;"
```

- [ ] **Step 6: Propose commit**

```
feat!: remove flexible_dates flag — dates absent now trigger LLM period planning (breaking contract, see ADR-007)
```

---

### Task 8: End-to-end verification (no commit)

**Files:** none touched (verification only)

- [ ] **Step 1:** `uv run pytest` green.
- [ ] **Step 2:** Deploy branch to VM (owner runs `./scripts/deploy.sh` after merging PR to dev, or test locally): start server + worker, POST a no-dates trip (curl from README, minus flexible_dates) and confirm in `trip_history.package_json`: `tool_calls` populated, ≥1 flight, corpus present, curated subset sane, email received with appendix.
- [ ] **Step 3:** POST a fixed-dates trip and confirm period planning is skipped (exactly one flight probe in `tool_calls`).
- [ ] **Step 4:** Owner reviews output quality (spec success criteria).

---

## Self-Review

- Spec coverage: F1→Task 1+5, F2→Task 5 prompts, F3→Task 3 (+models Task 2), F4→Tasks 4+5, F5→Task 5, F6→Task 6, F7→Task 7, E2E/success criteria→Task 8. Knowledge/budget explicitly Phase 2 (absent by design).
- Placeholders: none — the two flagged spots (Task 3 prompt signature correction, Task 7 base payload) carry explicit instructions inline.
- Type consistency: `AllowedResources`/`ValidationReport`/`sanitize_windows` (T1) match T3/T5 usage; models (T2) match prompts/orchestrator (T5); `dedupe_cap`/`maps.research(query)`/`places.search(destination=...)` (T4) match T5 call sites; `appendix`/`sections_map` (T5) match T6 rendering.
