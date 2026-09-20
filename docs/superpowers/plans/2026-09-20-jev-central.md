# Jev-centrale Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jev fa da orchestratore decisionale (router + scorer + gate), LLM resta solo per testo.

**Architecture:** Nuovo `DecisionClient` (`POST /v1/systemone`) separato da `LLMClient`; `TripOrchestrator` chiama Jev dietro flag con fallback agli `extract()` esistenti; armor di grounding invariato.

**Tech Stack:** Python >=3.13 via `uv run`, FastAPI, ARQ, pydantic v2, httpx, pytest + pytest-asyncio + fakeredis.

**Spec:** `docs/superpowers/specs/2026-09-20-jev-central-design.md`

## Global Constraints

- Python >= 3.13, run with `uv run <cmd>`, never `pip install`, never create `.venv` in workspace.
- Tests: `uv run pytest` (`asyncio_mode=auto`, `pythonpath=["."]`).
- Config via `.env` (`NOSTOS_` prefix) in `src/settings.py`; `NOSTOS_API_TOKEN` empty = auth disabled.
- Keep `validate_resources` + allow-list + `_is_junk_link` + `strip_bracket_ids` armor; no invented URLs.
- Pin Jev versioned ID `jev-1.13.0`, never alias `jev-latest`.
- Email template stays in `src/services/templates/email.html`, loaded via `load_email_template()`.

---

## File structure

- `src/services/apis/decisions.py` (new): `DecisionQuestion`, `DecisionResult`, `JevClient`, `build_decision_client`, `apply_thresholds`. One responsibility: parlare TypeSafe, nient'altro.
- `src/settings.py` (modify): 4 campi `decision_provider`, `typesafe_api_key`, `decision_model`, `decision_timeout`.
- `src/core/decision_router.py` (new): `build_router_state(trip)`, `ROUTER_QUESTIONS`, `route_trip(state, client)` con soglie 0.85/0.6. Solo mapping JSON→decisioni.
- `src/core/decision_scoring.py` (new): `score_flights`, `score_pois`, `pick_best`. Solo ordinamento candidati SerpAPI.
- `src/core/orchestrator.py` (modify): ramo flag `decision_provider==jev` → router/scorer/gate, else path esistente intatto.
- `src/infrastructure/worker.py` + `.env.example` (modify): plumbing flag, fail-fast log.
- Tests: `tests/test_decisions.py`, `tests/test_decision_router.py`, `tests/test_decision_scoring.py`, extend `tests/test_orchestrator.py` via fakes.

---

### Task 1: DecisionClient + settings

**Files:**
- Modify: `src/settings.py:46-68`
- Create: `src/services/apis/decisions.py`
- Test: `tests/test_decisions.py`

**Interfaces:**
- Consumes: `src.settings.Settings`
- Produces: `JevClient(state: dict, questions: dict) -> dict`, `build_decision_client(settings) -> JevClient | None`, `apply_threshold(prob: float) -> str` returning `"auto"|"review"|"fallback"`

- [ ] **Step 1: Write the failing test**

```python
from src.services.apis.decisions import apply_threshold

def test_apply_threshold_bands():
    assert apply_threshold(0.90) == "auto"
    assert apply_threshold(0.70) == "review"
    assert apply_threshold(0.50) == "fallback"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decisions.py::test_apply_threshold_bands -v`
Expected: FAIL with "No module named src.services.apis.decisions"

- [ ] **Step 3: Write minimal implementation**

```python
"""Jev DecisionClient: POST /v1/systemone, state + questions."""
import httpx

SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
PINNED_MODEL = "jev-1.13.0"

def apply_threshold(prob: float) -> str:
    if prob >= 0.85:
        return "auto"
    if prob >= 0.60:
        return "review"
    return "fallback"

class JevError(RuntimeError):
    pass

class JevClient:
    def __init__(self, api_key: str, model: str = PINNED_MODEL, timeout: float = 5.0, client: httpx.AsyncClient | None = None):
        self._api_key = api_key
        self._model = model or PINNED_MODEL
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def decide(self, state: dict, questions: dict) -> dict:
        try:
            resp = await self._client.post(
                SYSTEMONE_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "state": state, "questions": questions},
            )
            resp.raise_for_status()
        except Exception as exc:
            raise JevError(f"jev decide failed: {type(exc).__name__}: {exc}") from exc
        data = resp.json()
        return {"model": data.get("model", self._model), "answers": data.get("answers", data)}

def build_decision_client(settings) -> JevClient | None:
    if getattr(settings, "decision_provider", "llm-fallback") != "jev":
        return None
    if not getattr(settings, "typesafe_api_key", ""):
        return None
    return JevClient(api_key=settings.typesafe_api_key, model=settings.decision_model, timeout=settings.decision_timeout)
```

Settings addition in `src/settings.py` after `ollama_model` line:

```python
    decision_provider: str = "llm-fallback"
    typesafe_api_key: str = ""
    decision_model: str = "jev-1.13.0"
    decision_timeout: float = 5.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_decisions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/apis/decisions.py src/settings.py tests/test_decisions.py
git commit -m "feat: add Jev DecisionClient with thresholds and fallback builder"
```

### Task 2: Router state + questions (3 esempi come fixture)

**Files:**
- Create: `src/core/decision_router.py`
- Test: `tests/test_decision_router.py`

**Interfaces:**
- Consumes: `src.core.schemas.TripResponse`, `JevClient.decide`
- Produces: `build_router_state(trip: TripResponse) -> dict`, `ROUTER_QUESTIONS: dict`, `async route_trip(trip, client) -> dict` with keys `decisions`, `bands`, `model`

- [ ] **Step 1: Write the failing test**

```python
from src.core.decision_router import build_router_state, ROUTER_QUESTIONS
from src.core.schemas import TripResponse, TripStatus

def _trip():
    return TripResponse(id="t1", status=TripStatus.PENDING, received_at="2026-09-20T00:00:00+00:00",
        email="a@b.it", destination="Creta", departure_location="Italy",
        start_date="2027-07-30", end_date="2027-08-30", flexible_dates=False,
        travelers_count=2, travelers_type="coppia", free_text="cibo e tradizioni locali, mare e relax, ritmo lento, lontano dalle folle, van")

def test_router_state_and_questions():
    state = build_router_state(_trip())
    assert state["destination"] == "Creta"
    assert "van" in state["free_text"]
    assert ROUTER_QUESTIONS["travel_mode"]["type"] == "choice"
    assert ROUTER_QUESTIONS["needs_flights"]["type"] == "bool"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decision_router.py -v`
Expected: FAIL with "No module named src.core.decision_router"

- [ ] **Step 3: Write minimal implementation**

```python
"""Router: TripResponse -> Jev state + atomic questions."""
from src.core.schemas import TripResponse
from src.services.apis.decisions import apply_threshold

ROUTER_QUESTIONS = {
    "travel_mode": {"type": "choice", "choices": ["fixed", "road_trip", "van_life", "sailing", "mixed"], "instructions": "Modalità prevalente da free_text e campi form."},
    "needs_flights": {"type": "bool", "instructions": "True se serve volo per arrivare (paese diverso, isola, lunghe distanze)."},
    "pace": {"type": "choice", "choices": ["rilassato", "moderato", "intenso"], "instructions": "Ritmo del viaggio."},
    "avoids_crowds": {"type": "bool", "instructions": "True se cerca posti autentici lontano dalle folle."},
    "stay_fit": {"type": "choice", "choices": ["van", "camping", "homestay", "hotel", "boat"], "instructions": "Pernottamento più adatto."},
    "budget_sensitive": {"type": "bool", "instructions": "True se budget limitato o sensibilità prezzo esplicita."},
}

def build_router_state(trip: TripResponse) -> dict:
    return {
        "destination": trip.destination or "",
        "departure_location": trip.departure_location or "",
        "start_date": trip.start_date or "",
        "end_date": trip.end_date or "",
        "flexible_dates": bool(trip.flexible_dates),
        "travelers_count": trip.travelers_count,
        "travelers_type": trip.travelers_type or "",
        "travel_mode_hint": trip.travel_mode or "",
        "stay_hint": trip.stay_preference or "",
        "budget_amount": trip.budget_amount or "",
        "free_text": trip.free_text or "",
    }

async def route_trip(trip: TripResponse, client) -> dict:
    state = build_router_state(trip)
    raw = await client.decide(state, ROUTER_QUESTIONS)
    answers = raw.get("answers", {})
    decisions, bands = {}, {}
    for key in ROUTER_QUESTIONS:
        item = answers.get(key, {})
        value = item.get("value") if isinstance(item, dict) else item
        prob = float(item.get("probability", 0.0)) if isinstance(item, dict) else 0.0
        decisions[key] = value
        bands[key] = apply_threshold(prob)
    return {"decisions": decisions, "bands": bands, "probs": {k: (answers.get(k, {}) or {}).get("probability", 0.0) if isinstance(answers.get(k), dict) else 0.0 for k in ROUTER_QUESTIONS}, "model": raw.get("model", "")}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_decision_router.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/decision_router.py tests/test_decision_router.py
git commit -m "feat: add Jev router state and atomic questions"
```

### Task 3: Scorer voli + POI

**Files:**
- Create: `src/core/decision_scoring.py`
- Test: `tests/test_decision_scoring.py`

**Interfaces:**
- Consumes: SerpAPI corpus items (`dict` con `price_eur`, `link`, `name`), Jev score `0..1`
- Produces: `pick_best_flight(flights: list[dict], scores: dict[str,float], budget_sensitive: bool) -> dict | None`, `pick_top_pois(items: list[dict], scores: dict[str,float], limit: int = 3) -> list[dict]`

- [ ] **Step 1: Write the failing test**

```python
from src.core.decision_scoring import pick_best_flight, pick_top_pois

def test_pick_best_flight_prefers_cheap_useful():
    flights = [
        {"link": "u1", "price_eur": 300},
        {"link": "u2", "price_eur": 120},
    ]
    best = pick_best_flight(flights, {"u1": 0.9, "u2": 0.8}, False)
    assert best["link"] == "u2"

def test_pick_top_pois_orders_by_score():
    items = [{"link": "a", "name": "A"}, {"link": "b", "name": "B"}]
    assert [i["link"] for i in pick_top_pois(items, {"a": 0.4, "b": 0.95})] == ["b", "a"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decision_scoring.py -v`
Expected: FAIL with "No module named src.core.decision_scoring"

- [ ] **Step 3: Write minimal implementation**

```python
"""Scoring: combina score Jev 0..1 con prezzo in codice. Mai inventare link."""

def pick_best_flight(flights: list[dict], scores: dict[str, float], budget_sensitive: bool) -> dict | None:
    if not flights:
        return None
    price_weight = 2.0 if budget_sensitive else 1.0
    prices = [f.get("price_eur") for f in flights if isinstance(f.get("price_eur"), (int, float))]
    pmax = max(prices) if prices else 1.0
    def cost(f: dict) -> float:
        s = float(scores.get(f.get("link", ""), 0.5))
        p = f.get("price_eur")
        norm = (float(p) / pmax) if isinstance(p, (int, float)) and pmax else 1.0
        return norm * price_weight - s
    return min(flights, key=cost)

def pick_top_pois(items: list[dict], scores: dict[str, float], limit: int = 3) -> list[dict]:
    ranked = sorted(items, key=lambda i: float(scores.get(i.get("link", ""), 0.5)), reverse=True)
    seen: set[str] = set()
    out: list[dict] = []
    for it in ranked:
        link = it.get("link") or ""
        if not link or link in seen:
            continue
        seen.add(link)
        out.append(it)
        if len(out) >= limit:
            break
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_decision_scoring.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/decision_scoring.py tests/test_decision_scoring.py
git commit -m "feat: add flight and POI scoring helpers"
```

### Task 4: Wiring orchestratore dietro flag con fallback

**Files:**
- Modify: `src/core/orchestrator.py:162-210`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `route_trip`, `JevClient`, `pick_best_flight`, `pick_top_pois`
- Produces: stesso comportamento esterno; `package["tool_calls"]` include `{"engine": "jev-router", "model": ..., "decisions": ..., "bands": ...}`; fallback a path esistente se `client is None` o `JevError` o banda `fallback` su `travel_mode`/`needs_flights`.

- [ ] **Step 1: Write the failing test**

```python
import asyncio
from src.core.decision_router import build_router_state

class _FakeJev:
    async def decide(self, state, questions):
        return {"model": "jev-1.13.0", "answers": {
            "travel_mode": {"value": "van_life", "probability": 0.92},
            "needs_flights": {"value": True, "probability": 0.88},
            "pace": {"value": "rilassato", "probability": 0.9},
            "avoids_crowds": {"value": True, "probability": 0.87},
            "stay_fit": {"value": "van", "probability": 0.91},
            "budget_sensitive": {"value": False, "probability": 0.7},
        }}

def test_route_trip_fake_jev():
    from src.core.schemas import TripResponse, TripStatus
    from src.core.decision_router import route_trip
    trip = TripResponse(id="t1", status=TripStatus.PENDING, received_at="2026-09-20T00:00:00+00:00",
        email="a@b.it", destination="Creta", departure_location="Italy", free_text="van mare relax")
    out = asyncio.run(route_trip(trip, _FakeJev()))
    assert out["decisions"]["travel_mode"] == "van_life"
    assert out["model"] == "jev-1.13.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py::test_route_trip_fake_jev -v`
Expected: FAIL with "function not defined" finché il test non è nel file (aggiungerlo in coda a `tests/test_orchestrator.py`), poi PASS sul router.

- [ ] **Step 3: Write minimal implementation**

In `TripOrchestrator.run`, dopo `update_status RUNNING`, inserire ramo:

```python
from src.core.decision_router import route_trip
from src.services.apis.decisions import JevError, build_decision_client
from src.settings import get_settings

decision_client = build_decision_client(get_settings())
jev_route = None
if decision_client is not None:
    try:
        jev_route = await route_trip(trip, decision_client)
        tool_calls_jev = {"engine": "jev-router", "model": jev_route.get("model", ""), "decisions": jev_route["decisions"], "bands": jev_route["bands"]}
    except JevError:
        jev_route = None
```

Se `jev_route is None` o `bands[travel_mode]==fallback` e `bands[needs_flights]==fallback` → path esistente invariato. Altrimenti: usa `decisions[travel_mode]` al posto di `intent.travel_mode` per `_build_places_query` e query rental, e `decisions[needs_flights]` per saltare matrice voli; dopo corpus, score voli/POI via `pick_best_flight`/`pick_top_pois` prima di `_curate`; logga `tool_calls_jev` in `research["tool_calls"]`. Validazione allow-list e template invariati.

- [ ] **Step 4: Run tests to verify nothing breaks**

Run: `uv run pytest tests/test_orchestrator.py tests/test_decisions.py tests/test_decision_router.py tests/test_decision_scoring.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: wire Jev router behind flag with LLM fallback"
```

### Task 5: Worker, env, regressione finale

**Files:**
- Modify: `src/infrastructure/worker.py:65-73`, `.env.example`
- Test: full suite

**Interfaces:**
- Consumes: `Settings.decision_provider`
- Produces: log `decision provider + model` allo startup, nessun crash se `typesafe_api_key` vuota e provider `llm-fallback`.

- [ ] **Step 1: Extend startup assertion**

```python
settings = get_settings()
logger.info("decision provider: %s, model: %s", settings.decision_provider, settings.decision_model)
```

`.env.example` append:

```bash
NOSTOS_DECISION_PROVIDER=llm-fallback
NOSTOS_TYPESAFE_API_KEY=
NOSTOS_DECISION_MODEL=jev-1.13.0
NOSTOS_DECISION_TIMEOUT=5.0
```

- [ ] **Step 2: Run full suite**

Run: `uv run pytest -q`
Expected: PASS (stesso baseline; i nuovi test aggiunti passano, nessun contract rotto)

- [ ] **Step 3: Commit**

```bash
git add src/infrastructure/worker.py .env.example
git commit -m "chore: wire decision provider flag and env example"
```
