# tests/test_research_rescue.py — research-rescue batch R1–R4.
from src.core.models import Curation, ResolvedDestinations, ResolvedPlace, TripIntent
from src.core.orchestrator import TripOrchestrator
from src.core.schemas import TripStatus
from tests.fakes import FakeDatabase, FakeEmailSender, FakeLLM, make_store, make_trip
from tests.test_orchestrator import EMAIL


def _van_intent(**overrides):
    base = dict(destination="Scozia", travel_mode="van_life", accommodation_style="van")
    base.update(overrides)
    return TripIntent(**base)


def _orch(store, llm, trip_id):
    return TripOrchestrator(store=store, llm_client=llm, email_sender=FakeEmailSender(),
                            database=FakeDatabase(), trip_id=trip_id)


# --- R1: explore per destination + fallback ---

async def test_explore_splits_per_destination(monkeypatch):
    """Joined query ('Edimburgo e Inverness') must never be issued; each city is
    queried separately and anchors are gathered across both."""
    store = make_store()
    trip = await store.create(make_trip())
    orch = _orch(store, FakeLLM(response=TripIntent(destination="Scozia")), trip.id)
    seen = []

    async def fake_research(query, **kwargs):
        seen.append(query)
        if "Edimburgo e Inverness" in query:
            raise AssertionError(f"joined query must not be issued: {query!r}")
        city = query.split(" in ")[-1]
        return [{"name": f"POI {city}", "type": "t", "rating": 4.5,
                 "link": f"https://example.com/{city}"}]

    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_research)
    resolved = ResolvedDestinations(
        destinations=[ResolvedPlace(name="Edimburgo"), ResolvedPlace(name="Inverness")],
        rationale="t",
    )
    tool_calls: list[dict] = []
    anchors = await orch._explore("Edimburgo e Inverness", tool_calls, resolved=resolved)

    assert len(anchors) == 2
    assert {a["name"] for a in anchors} == {"POI Edimburgo", "POI Inverness"}
    logged = [tc["params"]["q"] for tc in tool_calls if "result_count" in tc]
    assert logged == ["quartieri e luoghi chiave in Edimburgo",
                      "quartieri e luoghi chiave in Inverness"]


async def test_explore_fallback_when_total_empty(monkeypatch):
    """Total-empty anchors trigger ONE plain fallback explore per destination."""
    store = make_store()
    trip = await store.create(make_trip())
    orch = _orch(store, FakeLLM(response=TripIntent(destination="Scozia")), trip.id)
    seen = []

    async def fake_research(query, **kwargs):
        seen.append(query)
        return []

    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_research)
    resolved = ResolvedDestinations(
        destinations=[ResolvedPlace(name="Edimburgo"), ResolvedPlace(name="Inverness")],
        rationale="t",
    )
    tool_calls: list[dict] = []
    anchors = await orch._explore("Edimburgo e Inverness", tool_calls, resolved=resolved)

    assert anchors == []
    assert "cose da vedere a Edimburgo" in seen
    assert "cose da vedere a Inverness" in seen
    assert not any("Edimburgo e Inverness" in q for q in seen), "joined query must never be issued"


async def test_explore_falls_back_to_destination_string_without_resolved(monkeypatch):
    """Empty resolved list -> single query on the effective destination string."""
    store = make_store()
    trip = await store.create(make_trip())
    orch = _orch(store, FakeLLM(response=TripIntent(destination="Tokyo")), trip.id)
    seen = []

    async def fake_research(query, **kwargs):
        seen.append(query)
        return [{"name": "POI", "type": "t", "rating": 4.5, "link": "https://example.com/poi"}]

    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_research)
    tool_calls: list[dict] = []
    anchors = await orch._explore(
        "Tokyo", tool_calls, resolved=ResolvedDestinations(destinations=[], rationale=""))

    assert len(anchors) == 1
    assert seen == ["quartieri e luoghi chiave in Tokyo"]


# --- R2: van stays query that survives ---

async def test_van_query_chain_error_then_alternate_then_generic(monkeypatch):
    """Mode query errors -> alternate 'campsite' form -> generic retry last."""
    trip = make_trip(destination="Scozia")
    store = make_store()
    await store.create(trip)
    orch = _orch(store, FakeLLM(response=_van_intent()), trip.id)
    queries = []

    async def fake_places(**kwargs):
        q = kwargs.get("query")
        queries.append(q)
        if q.startswith("campeggio "):
            raise RuntimeError("serpapi down")
        if q.startswith("campsite "):
            return []
        assert q.startswith("hotels in ")
        return [{"name": "Hotel X", "price_per_night_eur": 80, "link": "https://example.com/h"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "POI", "type": "t", "rating": 4.5, "link": "https://example.com/poi"}]

    async def fake_flights(*a, **k):
        return []

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    tool_calls: list[dict] = []
    result = await orch._execute_searches(
        trip, _van_intent(), [], [("2026-09-01", "2026-09-10")],
        [{"name": "POI", "type": "t", "rating": 4.5, "link": "https://example.com/poi"}],
        tool_calls, resolved=ResolvedDestinations(destinations=[], rationale=""),
        departure_codes=[])

    stays_queries = [q for q in queries if not (q or "").startswith("noleggio camper van")]
    assert stays_queries == ["campeggio Scozia", "campsite Scozia", "hotels in Scozia"]
    hotels_tc = [tc for tc in tool_calls if tc.get("engine") == "google_hotels"
                 and not tc.get("params", {}).get("rental")]
    assert [tc["params"]["q"] for tc in hotels_tc] == stays_queries
    assert hotels_tc[0].get("error") == "RuntimeError"
    assert result["corpus"]["places"], "generic retry must fill the stays corpus"


async def test_van_mode_query_is_simplified(monkeypatch):
    trip = make_trip(destination="Scozia")
    store = make_store()
    await store.create(trip)
    orch = _orch(store, FakeLLM(response=_van_intent()), trip.id)
    assert orch._build_places_query("Scozia", _van_intent(), trip) == "campeggio Scozia"


# --- R3: failed searches leave a trace ---

async def test_guarded_error_leaves_trace_without_message(monkeypatch):
    """A raising search appends an error entry (class name only, no message)."""
    trip = make_trip()
    store = make_store()
    await store.create(trip)
    intent = TripIntent(destination="Tokyo", departure_airport_code="MXP",
                        destination_airport_code="HND")
    orch = _orch(store, FakeLLM(response=intent), trip.id)

    async def raise_flights(*a, **k):
        raise RuntimeError("serpapi down: key=secret")

    async def fake_maps(query, **kwargs):
        return [{"name": "POI", "type": "t", "rating": 4.5, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Hotel X", "price_per_night_eur": 90, "link": "https://example.com/h"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", raise_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    tool_calls: list[dict] = []
    await orch._execute_searches(
        trip, intent, [], [("2026-09-01", "2026-09-10")],
        [{"name": "POI", "type": "t", "rating": 4.5, "link": "https://example.com/poi"}],
        tool_calls, resolved=ResolvedDestinations(destinations=[], rationale=""),
        departure_codes=["MXP"])

    flight_tc = [tc for tc in tool_calls if tc.get("engine") == "google_flights"]
    assert flight_tc == [{"engine": "google_flights",
                          "params": {"departure_id": "MXP", "arrival_id": "HND",
                                     "outbound_date": "2026-09-01", "return_date": "2026-09-10"},
                          "error": "RuntimeError"}]
    assert "secret" not in repr(tool_calls) and "serpapi down" not in repr(tool_calls)
    # success entries stay byte-identical
    for tc in tool_calls:
        if "error" not in tc and not tc.get("skipped"):
            assert set(tc) == {"engine", "params", "result_count"}


# --- R4: honest abort on hollow curated results ---

async def test_flight_only_curated_aborts_without_email(monkeypatch):
    """Curated maps+places both empty (LLM rejected everything) -> abort, no send."""
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(
        response=TripIntent(destination="Scozia", departure_airport_code="MXP",
                            destination_airport_code="EDI"),
        email_response=EMAIL,
        responses={Curation: Curation(flight_indices=[0], poi_indices=[], stay_indices=[])},
    )
    email = FakeEmailSender()
    db = FakeDatabase()

    async def fake_flights(*a, **k):
        return [{"airline": "A", "from": "MXP", "to": "EDI", "departure_date": "2026-09-01",
                 "price_eur": 120, "link": "https://example.com/f"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "POI", "type": "t", "rating": 4.5, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Hotel X", "price_per_night_eur": 90, "link": "https://example.com/h"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    orch = TripOrchestrator(store=store, llm_client=llm, email_sender=email,
                            database=db, trip_id=trip.id)
    await orch.run()

    assert email.sent == []
    assert db.saved == []
    got = await store.get(trip.id)
    assert got.status == TripStatus.ERROR
    assert "only a flight was found" in (got.result or "")
    assert db.status.get(trip.id) == TripStatus.ERROR.value
