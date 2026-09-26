# Itinerario strutturato Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** L'email guadagna la sezione itinerario (fasi condensate con card grounded + transizioni libere).

**Architecture:** Nuovi modelli `DayStop`/`TripPlan` + validatore puro; nuovo `extract()` Planner dopo `_curate`; renderer `_render_itinerary` riusando `_render_card`; sezione additiva con skip silenzioso se piano vuoto.

**Tech Stack:** Python >=3.13 via `uv run`, pydantic v2, pytest + pytest-asyncio + fakeredis.

**Spec:** `docs/superpowers/specs/2026-09-20-jev-itinerary-design.md`

## Global Constraints

- Python >= 3.13, run with `uv run <cmd>`, never `pip install`, never create `.venv` in workspace.
- Tests: `uv run pytest` (`asyncio_mode=auto`, `pythonpath=["."]`).
- Config via `.env` (`NOSTOS_` prefix); nessuna nuova env in fase 2.
- Mai inventare link: `stop_refs` solo indici curati, `transition` mai con URL.
- Template solo in `src/services/templates/email.html` via `load_email_template()`.
- Piano vuoto → sezione assente, mai abortire il trip.
- Contract test input API invariato.

---

## File structure

- `src/core/models.py` (append): `DayStop`, `TripPlan`. Solo schemi.
- `src/core/trip_plan.py` (new): `sanitize_plan(plan: TripPlan, flight_n: int, maps_n: int, places_n: int) -> TripPlan`, `strip_url_transitions`. Solo validazione pura.
- `src/core/prompts/__init__.py` (append): `build_plan_prompt(...)`. Solo testo prompt.
- `src/core/orchestrator.py` (modify): `_plan_itinerary` + chiamata dopo `research["curated"] = curated`, `package["trip_plan"]`, passaggio a `_compose_email`.
- `src/services/apis/email.py` (modify): `_render_itinerary(plan_days, cards_by_link)` + hook in `build_html_email`.
- `src/services/templates/email.html` (modify): placeholder `$itinerary_section` tra `$resource_groups` e `$rental_section`.
- Tests: `tests/test_trip_plan.py` (new), extend `tests/test_email_rendering.py`, fixture Creta in `tests/test_itinerary_fixture.py` (new).

---

### Task 1: Modelli + validatore puro

**Files:**
- Modify: `src/core/models.py` (append dopo `DepartureAirports`)
- Create: `src/core/trip_plan.py`
- Test: `tests/test_trip_plan.py`

**Interfaces:**
- Consumes: `Curation`-style index convention (zero-based sul curato)
- Produces: `DayStop(day_label: str, stop_refs: list[int], transition: str = "")`, `TripPlan(days: list[DayStop], rationale: str = "")`, `sanitize_plan(plan, flight_n, maps_n, places_n) -> TripPlan`

`sanitize_plan` semantics (verbatim): per ogni day tieni `stop_refs` con `0 <= i < (flight_n + maps_n + places_n)`? NO — gli indici sono per-categoria come `Curation` (flight/poi/stay separati). Perciò `DayStop` usa refs con categoria esplicita:

```python
class DayStop(BaseModel):
    day_label: str = Field(description="Intervallo + zona, es. 'Giorni 1-7 · Heraklion e dintorni'")
    flight_refs: list[int] = Field(default_factory=list)
    poi_refs: list[int] = Field(default_factory=list)
    stay_refs: list[int] = Field(default_factory=list)
    transition: str = Field(default="", description="Logica spostamento in italiano, mai URL")
```

`sanitize_plan`: filtra ogni lista ref per-categoria contro le lunghezze curate, logga warning per drop (usa `logging.getLogger("nostos.trip_plan")`), svuota `transition` se matcha `https?://|www\.`, tronca `days[:7]`, scarta voci con zero refs e transizione vuota.

- [ ] **Step 1: Write the failing test**

```python
from src.core.models import TripPlan, DayStop
from src.core.trip_plan import sanitize_plan

def test_sanitize_drops_bad_refs_and_url_transition():
    plan = TripPlan(days=[
        DayStop(day_label="Giorni 1-7 · X", poi_refs=[0, 9], stay_refs=[0],
                transition="dettagli su https://esempio.it/x"),
    ])
    clean = sanitize_plan(plan, flight_n=1, maps_n=3, places_n=2)
    assert clean.days[0].poi_refs == [0]
    assert clean.days[0].stay_refs == [0]
    assert clean.days[0].transition == ""

def test_sanitize_caps_to_7_and_drops_empty():
    plan = TripPlan(days=[
        DayStop(day_label=f"G{i}", poi_refs=[0]) for i in range(9)
    ] + [DayStop(day_label="vuota")])
    clean = sanitize_plan(plan, flight_n=0, maps_n=3, places_n=0)
    assert len(clean.days) == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_trip_plan.py -v`
Expected: FAIL with "No module named src.core.trip_plan"

- [ ] **Step 3: Write minimal implementation**

Append in `src/core/models.py`:

```python
class DayStop(BaseModel):
    day_label: str = Field(description="Intervallo + zona, es. 'Giorni 1-7 · Heraklion e dintorni'")
    flight_refs: list[int] = Field(default_factory=list, description="Indici zero-based nei voli curati")
    poi_refs: list[int] = Field(default_factory=list, description="Indici zero-based nei POI curati")
    stay_refs: list[int] = Field(default_factory=list, description="Indici zero-based negli alloggi curati")
    transition: str = Field(default="", description="Logica spostamento in italiano, mai URL")


class TripPlan(BaseModel):
    days: list[DayStop] = Field(default_factory=list, description="Max 7 voci condensate")
    rationale: str = Field(default="", description="Perché questa articolazione, in italiano")
```

Create `src/core/trip_plan.py`:

```python
"""TripPlan validation: per-category ref filtering + URL-free transitions."""
import logging
import re

from src.core.models import TripPlan

logger = logging.getLogger("nostos.trip_plan")

MAX_DAYS = 7
_URL_RE = re.compile(r"https?://|www\.")

def sanitize_plan(plan: TripPlan, flight_n: int, maps_n: int, places_n: int) -> TripPlan:
    kept = []
    for day in plan.days[:MAX_DAYS]:
        flights = [i for i in day.flight_refs if 0 <= i < flight_n]
        pois = [i for i in day.poi_refs if 0 <= i < maps_n]
        stays = [i for i in day.stay_refs if 0 <= i < places_n]
        dropped = (len(day.flight_refs) - len(flights) + len(day.poi_refs) - len(pois)
                   + len(day.stay_refs) - len(stays))
        if dropped:
            logger.warning("trip plan ref %d out of range dropped (%s)", dropped, day.day_label)
        transition = day.transition
        if transition and _URL_RE.search(transition):
            logger.warning("trip plan URL stripped from transition (%s)", day.day_label)
            transition = ""
        if not flights and not pois and not stays and not transition:
            continue
        kept.append(day.model_copy(update={"flight_refs": flights, "poi_refs": pois,
                                            "stay_refs": stays, "transition": transition}))
    return plan.model_copy(update={"days": kept})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_trip_plan.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/models.py src/core/trip_plan.py tests/test_trip_plan.py
git commit -m "feat: add TripPlan models and sanitize validator"
```

### Task 2: Planner prompt + orchestratore

**Files:**
- Modify: `src/core/prompts/__init__.py` (append `build_plan_prompt`)
- Modify: `src/core/orchestrator.py` (add `_plan_itinerary`, call dopo `research["curated"] = curated`, `package["trip_plan"]`)
- Test: `tests/test_itinerary_planner.py`

**Interfaces:**
- Consumes: `TripPlan`, `sanitize_plan`, `self._llm.extract`, `self._render_flights/_render_maps/_render_places`
- Produces: `async _plan_itinerary(self, trip, intent, curated) -> TripPlan` (vuoto se no date o eccezione)

`build_plan_prompt(trip, intent, flights_block, maps_block, places_block, trip_days: int)` (verbatim body):

```python
def build_plan_prompt(trip, intent, flights_block: str, maps_block: str, places_block: str, trip_days: int) -> str:
    return f"""Articola questo viaggio in fasi visitabili per l'email.
    Durata: {trip_days} giorni. Travel mode: {intent.travel_mode or 'not specified'}.
    Interessi: {', '.join(intent.interests) or 'not specified'}.
    Risorse curate (riferisci SOLO questi indici zero-based per categoria):
    Voli:
    {flights_block}
    POI:
    {maps_block}
    Alloggi:
    {places_block}
    Regole: max 7 voci che coprono arrivo, permanenza e rientro; ogni voce 1-3 refs totali;
    day_label con intervallo + zona (es. 'Giorni 1-7 · Heraklion e dintorni');
    transition di una riga su spostamenti/pernottamenti, senza inventare servizi e SENZA url.
    Per fixed preferisci fasi per zone; per van_life/road_trip tratte con pernottamenti a bordo;
    per sailing tratte costiere. Rispondi solo con le voci utili."""
```

`_plan_itinerary` (verbatim, 1 tentativo, niente retry):

```python
async def _plan_itinerary(self, trip: TripResponse, intent: TripIntent, curated: dict) -> TripPlan:
    from src.core.models import TripPlan
    from src.core.prompts import build_plan_prompt
    from src.core.trip_plan import sanitize_plan
    from datetime import date
    if not trip.start_date or not trip.end_date:
        return TripPlan()
    try:
        days = (date.fromisoformat(trip.end_date) - date.fromisoformat(trip.start_date)).days + 1
    except ValueError:
        return TripPlan()
    if days <= 0:
        return TripPlan()
    try:
        raw = await self._llm.extract(
            build_plan_prompt(trip, intent,
                              self._render_flights(curated["flights"], numbered=True),
                              self._render_maps(curated["maps"], numbered=True),
                              self._render_places(curated["places"], numbered=True),
                              days),
            TripPlan,
        )
    except Exception as exc:
        logger.warning("trip plan skipped: %s: %s", type(exc).__name__, exc)
        return TripPlan()
    return sanitize_plan(raw, len(curated["flights"]), len(curated["maps"]), len(curated["places"]))
```

Call site dopo `research["curated"] = curated` (orchestrator.py:246):

```python
trip_plan = await self._plan_itinerary(trip, intent, curated)
research["trip_plan"] = trip_plan
```

In `_compose_email`, dopo `package` dict esistente, aggiungere `"trip_plan": research.get("trip_plan", TripPlan()).model_dump(),` e log tool call `{"engine": "jev-itinerary", "days": len(trip_plan.days)}` oppure `{"engine": "jev-itinerary", "skipped": True}` in `research["tool_calls"]`.

- [ ] **Step 1: Write the failing test**

```python
import asyncio
from src.core.models import TripPlan, DayStop

class _FakeLLM:
    async def extract(self, prompt, model):
        assert "Giorni" in prompt or "fasi" in prompt
        return TripPlan(days=[DayStop(day_label="Giorni 1-7 · X", poi_refs=[0], transition="tappe corte.")])

def test_plan_itinerary_no_dates_returns_empty():
    from src.core.schemas import TripResponse, TripStatus
    from src.core.orchestrator import TripOrchestrator
    orch = TripOrchestrator.__new__(TripOrchestrator)
    trip = TripResponse(id="t", status=TripStatus.PENDING, received_at="2026-09-20T00:00:00+00:00",
        email="a@b.it", destination="Creta", free_text="van")
    plan = asyncio.run(orch._plan_itinerary(trip, __import__("src.core.models", fromlist=["TripIntent"]).TripIntent(), {"flights": [], "maps": [], "places": []}))
    assert plan.days == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_itinerary_planner.py -v`
Expected: FAIL with "has no attribute '_plan_itinerary'"

- [ ] **Step 3: Write minimal implementation**

Code blocks above verbatim.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_itinerary_planner.py tests/test_trip_plan.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/prompts/__init__.py src/core/orchestrator.py tests/test_itinerary_planner.py
git commit -m "feat: add itinerary Planner step with silent skip"
```

### Task 3: Template + renderer

**Files:**
- Modify: `src/services/templates/email.html` (insert `$itinerary_section` tra `$resource_groups` e `$rental_section`)
- Modify: `src/services/apis/email.py` (add `_render_itinerary`, hook in `build_html_email`)
- Test: extend `tests/test_email_rendering.py`

**Interfaces:**
- Consumes: `plan.model_dump()` days + `resources_by_link: dict[str, dict]`
- Produces: `_render_itinerary(days: list[dict], cards_by_link: dict) -> str` ("" se vuoto)

Template insert dopo il blocco `<!-- Risorse -->` row e prima di `<!-- Noleggio van`:

```html
            <!-- Itinerario -->
            <tr>
              <td class="gutter" style="padding:0 36px;">
                $itinerary_section
              </td>
            </tr>
```

`_render_itinerary` (verbatim, self-contained):

```python
def _render_itinerary(days: list[dict], cards_by_link: dict[str, dict]) -> str:
    """Itinerary section: day_label + reused grounded cards + free transition.
    Entries with no valid cards render label + transition only. Empty plan -> ""."""
    blocks = []
    for day in days or []:
        label = day.get("day_label") or ""
        cards = [cards_by_link[link] for link in day.get("links", []) if link in cards_by_link][:3]
        transition = day.get("transition") or ""
        if not label and not cards and not transition:
            continue
        head = (f'<div style="font-family:\'Fraunces\',Georgia,serif;font-size:16px;font-weight:600;'
                f'color:#221D0F;margin:16px 0 8px;">{_e(label)}</div>' if label else "")
        cards_html = "".join(_render_card(c) for c in cards)
        trans_html = (f'<div class="d-desc" style="font-family:\'IBM Plex Sans\',Arial,sans-serif;'
                      f'font-size:13px;font-style:italic;line-height:1.55;color:#3B4956;margin-top:5px;">'
                      f'{_e(transition)}</div>' if transition else "")
        blocks.append(head + cards_html + trans_html)
    if not blocks:
        return ""
    head_all = ('<div class="d-heading" style="font-family:\'Fraunces\',Georgia,serif;font-size:19px;'
                'font-weight:600;color:#221D0F;line-height:1.4;">L\'itinerario</div>'
                '<div class="d-hairline" style="border-top:1px solid #D0DDE9;margin-top:18px;'
                'line-height:1px;font-size:0;">&nbsp;</div>')
    return head_all + "".join(blocks)
```

Caller in `build_html_email` prepara:

```python
plan_days = content.get("itinerary_days", [])
cards_by_link = {r.get("link"): r for r in content.get("resources", []) if r.get("link")}
```

e passa `itinerary_section=_render_itinerary(plan_days, cards_by_link)`. `_compose_email`
in orchestrator popola `content["itinerary_days"]` da `trip_plan` mappando refs→link curati:

```python
flight_links = [r["link"] for r in curated["flights"] if r.get("link")]
maps_links = [r["link"] for r in curated["maps"] if r.get("link")]
places_links = [r["link"] for r in curated["places"] if r.get("link")]
itinerary_days = []
for day in trip_plan.days:
    links = ([flight_links[i] for i in day.flight_refs if i < len(flight_links)]
             + [maps_links[i] for i in day.poi_refs if i < len(maps_links)]
             + [places_links[i] for i in day.stay_refs if i < len(places_links)])
    itinerary_days.append({"day_label": day.day_label, "links": links, "transition": day.transition})
content["itinerary_days"] = itinerary_days
```

- [ ] **Step 1: Write the failing test**

```python
from src.services.apis.email import _render_itinerary, _render_card  # noqa

def test_render_itinerary_empty_is_empty():
    assert _render_itinerary([], {}) == ""

def test_render_itinerary_reuses_cards():
    card = {"name": "Taverna X", "description": "cucina locale", "price": "", "link": "https://x.it"}
    html = _render_itinerary([{"day_label": "Giorni 1-7 · X", "links": ["https://x.it"], "transition": "tappe corte."}], {"https://x.it": card})
    assert "Giorni 1-7" in html and "Taverna X" in html and "tappe corte" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_email_rendering.py -v -k itinerary`
Expected: FAIL with "has no attribute '_render_itinerary'"

- [ ] **Step 3: Write minimal implementation**

Code blocks above verbatim.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_email_rendering.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/templates/email.html src/services/apis/email.py tests/test_email_rendering.py
git commit -m "feat: render itinerary section reusing grounded cards"
```

### Task 4: Body text + fixture Creta + regressione

**Files:**
- Modify: `src/core/orchestrator.py` (`_compose_body_text`: sezione "L'itinerario" dopo "Punti di partenza", prima del travel box)
- Create: `tests/test_itinerary_fixture.py`
- Test: full suite

**Interfaces:**
- Consumes: `content["itinerary_days"]`, `content["resources"]` nomi
- Produces: body text con day_label + nomi tappe + transizioni, senza link nuovi

Body insert dopo il blocco rentals e prima di `appendix` (verbatim):

```python
itinerary_days = email_content.get("itinerary_days", [])
if itinerary_days:
    lines.append("L'itinerario:")
    names_by_link = {r.get("link"): r.get("name") for r in email_content.get("resources", [])}
    for day in itinerary_days:
        lines.append(day.get("day_label", ""))
        for link in day.get("links", []):
            if link in names_by_link:
                lines.append(f"- {names_by_link[link]}")
        if day.get("transition"):
            lines.append(f"  {day['transition']}")
    lines.append("")
```

Fixture test (verbatim):

```python
def test_creta_fixture_email_has_4_phases_no_new_links():
    from src.services.apis.email import build_html_email
    resources = [
        {"name": "Volo easyJet · Milano – Heraklion", "description": "diretto", "price": "196 EUR", "link": "https://voli.it/f1"},
        {"name": "Taverna To Stachi", "description": "cucina cretese", "price": "", "link": "https://maps.it/t1"},
        {"name": "Spiaggia Elafonissi", "description": "mare quieto", "price": "", "link": "https://maps.it/s1"},
        {"name": "Campeggio Paleochora", "description": "sosta van", "price": "20 EUR/notte", "link": "https://stay.it/c1"},
    ]
    content = {"opening": "o", "understanding": "u", "resources": resources,
        "sections_map": {"flights": ["https://voli.it/f1"], "places": ["https://stay.it/c1"], "maps": ["https://maps.it/t1", "https://maps.it/s1"]},
        "itinerary_days": [
            {"day_label": "Giorni 1-7 · Heraklion e dintorni", "links": ["https://maps.it/t1"], "transition": "ritiro van e notti vicino Heraklion."},
            {"day_label": "Giorni 8-15 · Costa sud", "links": ["https://maps.it/s1", "https://stay.it/c1"], "transition": "discesa verso sud, tappe corte."},
        ],
        "appendix": {"groups": [], "source_links": []}, "cta": "c", "honest_note": "n",
        "travel_mode": "van_life", "mobility": [], "accommodation_style": "van", "feedback_link": ""}
    html = build_html_email(content)
    assert html.count("Giorni") == 2
    assert "Taverna To Stachi" in html and "Elafonissi" in html
    assert "https://voli.it/f1" in html
```

- [ ] **Step 1: Write the failing test**

Code block above in `tests/test_itinerary_fixture.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_itinerary_fixture.py -v`
Expected: FAIL (KeyError `itinerary_days` o sezione assente — o `Giorni` count 0)

- [ ] **Step 3: Write minimal implementation**

Body-text block above verbatim nel punto indicato.

- [ ] **Step 4: Run full suite**

Run: `uv run pytest -q`
Expected: PASS (baseline 227 passed + nuovi test)

- [ ] **Step 5: Commit**

```bash
git add src/core/orchestrator.py tests/test_itinerary_fixture.py
git commit -m "feat: itinerary in text body plus Creta fixture"
```
