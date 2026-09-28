from src.core.models import Curation, PeriodPlan, TripIntent
from src.core.orchestrator import TripOrchestrator
from src.core.schemas import TripStatus
from tests.fakes import FakeDatabase, FakeEmailSender, FakeLLM, make_store, make_trip

INTENT = TripIntent(
    destination="Tokyo",
    departure_airport_code="MXP",
    destination_airport_code="HND",
    interests=["cibo"],
    style=["autentico"],
    pace="moderato",
)

async def _run(orchestrator):
    await orchestrator.run()


def _make_llm():
    return FakeLLM(response=INTENT)


async def test_happy_path_sends_email_and_saves_history(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = _make_llm()
    email = FakeEmailSender()
    db = FakeDatabase()

    async def fake_flights(*args, **kwargs):
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01", "price_eur": 320, "link": "https://example.com/flight"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    orchestrator = TripOrchestrator(
        store=store,
        llm_client=llm,
        email_sender=email,
        database=db,
        trip_id=trip.id,
    )
    await _run(orchestrator)

    assert len(email.sent) == 1
    assert email.sent[0]["to"] == "test@example.com"
    assert len(db.saved) == 1
    assert db.saved[0]["trip_id"] == trip.id

    got = await store.get(trip.id)
    assert got.status == TripStatus.DONE
    assert db.status.get(trip.id) == TripStatus.DONE.value
    assert await store.claim(trip.id, ttl_seconds=300) is True

    done_updates = [u for u in db.status_updates.get(trip.id, []) if u.get("status") == TripStatus.DONE.value]
    assert done_updates, f"expected a DONE update, got {db.status_updates}"
    assert done_updates[0]["send_datetime"], "send_datetime must be set on success"
    from datetime import datetime as dt

    assert isinstance(done_updates[0]["send_datetime"], dt), "send_datetime must be a datetime object (asyncpg needs it)"
    assert done_updates[0]["duration_seconds"] >= 0


async def test_happy_path_saves_model_in_history(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = _make_llm()
    email = FakeEmailSender()
    db = FakeDatabase()

    async def one(*args, **kwargs):
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01", "price_eur": 320, "link": "https://example.com/flight"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", one)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    orchestrator = TripOrchestrator(
        store=store,
        llm_client=llm,
        email_sender=email,
        database=db,
        trip_id=trip.id,
        llm_model="qwen3:30b-a3b-instruct-2507-q4_K_M",
    )
    await _run(orchestrator)

    assert db.saved[0]["model"] == "qwen3:30b-a3b-instruct-2507-q4_K_M"


async def test_all_searches_empty_aborts_without_email(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT)
    email = FakeEmailSender()
    db = FakeDatabase()

    async def empty(*args, **kwargs):
        return []

    monkeypatch.setattr("src.core.orchestrator.flights.search", empty)
    monkeypatch.setattr("src.core.orchestrator.maps.research", empty)
    monkeypatch.setattr("src.core.orchestrator.places.search", empty)

    orchestrator = TripOrchestrator(
        store=store,
        llm_client=llm,
        email_sender=email,
        database=db,
        trip_id=trip.id,
    )
    await _run(orchestrator)

    assert email.sent == []
    assert db.saved == []
    got = await store.get(trip.id)
    assert got.status == TripStatus.ERROR
    assert "No resources" in got.result
    assert await store.claim(trip.id, ttl_seconds=300) is True


async def test_serpapi_errors_abort_without_email(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT)
    email = FakeEmailSender()
    db = FakeDatabase()

    async def raise_error(*args, **kwargs):
        raise RuntimeError("serpapi down")

    monkeypatch.setattr("src.core.orchestrator.flights.search", raise_error)
    monkeypatch.setattr("src.core.orchestrator.maps.research", raise_error)
    monkeypatch.setattr("src.core.orchestrator.places.search", raise_error)

    orchestrator = TripOrchestrator(
        store=store,
        llm_client=llm,
        email_sender=email,
        database=db,
        trip_id=trip.id,
    )
    await _run(orchestrator)

    assert email.sent == []
    assert db.saved == []
    got = await store.get(trip.id)
    assert got.status == TripStatus.ERROR
    assert "all searches failed" in got.result


async def test_llm_error_marks_trip_error():
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT, error=RuntimeError("llm down"))
    email = FakeEmailSender()
    db = FakeDatabase()

    orchestrator = TripOrchestrator(
        store=store,
        llm_client=llm,
        email_sender=email,
        database=db,
        trip_id=trip.id,
    )
    await _run(orchestrator)

    got = await store.get(trip.id)
    assert got.status == TripStatus.ERROR
    assert got.result is not None
    assert db.status.get(trip.id) == TripStatus.ERROR.value
    assert await store.claim(trip.id, ttl_seconds=300) is True

    err_updates = [u for u in db.status_updates.get(trip.id, []) if u.get("status") == TripStatus.ERROR.value]
    assert err_updates, f"expected an ERROR update, got {db.status_updates}"
    assert err_updates[0]["error_message"], "error_message must be persisted on failure"


async def test_already_claimed_returns_without_side_effects():
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT)
    email = FakeEmailSender()
    db = FakeDatabase()

    await store.claim(trip.id, ttl_seconds=300)

    orchestrator = TripOrchestrator(
        store=store,
        llm_client=llm,
        email_sender=email,
        database=db,
        trip_id=trip.id,
    )
    await _run(orchestrator)

    assert email.sent == []
    assert db.saved == []
    got = await store.get(trip.id)
    assert got.status == TripStatus.PENDING


async def test_no_dates_triggers_period_plan_and_multi_window_flight_probe(monkeypatch):
    from datetime import date, timedelta

    # Finestre relative a oggi: date fisse scadono e sanitize_windows le scarta.
    w1_start = (date.today() + timedelta(days=30)).isoformat()
    w1_end = (date.today() + timedelta(days=44)).isoformat()
    w2_start = (date.today() + timedelta(days=60)).isoformat()
    w2_end = (date.today() + timedelta(days=74)).isoformat()
    store = make_store()
    trip = await store.create(make_trip(start_date=None, end_date=None))
    llm = FakeLLM(
        response=INTENT,
        responses={PeriodPlan: PeriodPlan(windows=[
            {"start": w1_start, "end": w1_end, "rationale": "mild"},
            {"start": w2_start, "end": w2_end, "rationale": "cheaper"},
        ])},
    )

    seen_outbound_dates = []

    async def fake_flights(departure, destination, start_date, end_date, **kwargs):
        seen_outbound_dates.append(start_date)
        price = 400 if start_date == w1_start else 300
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": start_date,
                 "price_eur": price, "link": f"https://example.com/{start_date}"}]

    stay_windows = []

    async def fake_places(**kwargs):
        stay_windows.append(kwargs.get("check_in_date"))
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    email = FakeEmailSender()
    db = FakeDatabase()
    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=email,
                                    database=db, trip_id=trip.id)
    await _run(orchestrator)

    assert sorted(seen_outbound_dates) == sorted([w1_start, w2_start, w2_start])  # both windows probed + winner revalidation
    assert stay_windows[-1] == w2_start  # stays aligned to cheapest window
    assert email.sent and db.saved  # trip completes


async def test_unusable_period_plan_falls_back(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip(start_date=None, end_date=None))
    llm = FakeLLM(response=INTENT)  # default PeriodPlan(windows=[])

    seen = []

    async def fake_flights(*args, **kwargs):
        seen.append(kwargs.get("outbound_date") or args[2])
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "x",
                 "price_eur": 300, "link": "https://example.com/f"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=FakeEmailSender(),
                                    database=FakeDatabase(), trip_id=trip.id)
    await _run(orchestrator)

    assert len(seen) == 2  # fallback window probe + winner revalidation


async def test_start_only_trip_probes_one_way_flight_without_period_llm_call(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip(end_date=None))
    llm = FakeLLM(response=INTENT)

    flight_calls = []
    stay_kwargs = []

    async def fake_flights(*args, **kwargs):
        flight_calls.append((args, kwargs))
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01",
                 "price_eur": 320, "link": "https://example.com/f"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        stay_kwargs.append(kwargs)
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    email = FakeEmailSender()
    db = FakeDatabase()
    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=email,
                                    database=db, trip_id=trip.id)
    await _run(orchestrator)

    assert len(flight_calls) == 2  # matrix probe + winner revalidation of the same combo
    args, _ = flight_calls[0]
    assert args[2] == "2026-09-01"  # outbound = trip start
    assert args[3] is None  # end_date=None -> one-way search (type=2)
    assert stay_kwargs[-1].get("check_out_date") is None  # stays fall back to default window
    assert all(model is not PeriodPlan for _, model in llm.calls)  # no period-planning LLM call
    assert email.sent and db.saved  # trip completes


async def test_stages_run_in_order_and_package_records_tool_calls(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT)
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
    assert all(set(tc) == {"engine", "params", "result_count"}
               or set(tc) == {"engine", "revalidated", "reason"}  # winner revalidation entry
               for tc in package["tool_calls"])
    assert "corpus" in package and "curated" in package


async def test_curation_indices_out_of_range_are_dropped(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(
        response=INTENT,
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


# --- Validation gate: grounding of letter moments against the curated corpus ---


async def _run_with_searches(monkeypatch, llm, email, db, trip, store):
    async def fake_flights(*args, **kwargs):
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01",
                 "price_eur": 320, "link": "https://example.com/flight"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    orchestrator = TripOrchestrator(llm_client=llm, email_sender=email,
                                    database=db, trip_id=trip.id, store=store)
    await _run(orchestrator)


async def test_compose_letter_uses_large_token_budget(monkeypatch):
    """Letter moments are prose: compose must request headroom, or long
    letters truncate (prod ValidationError, trip ERROR)."""
    from src.core.models import LetterContent

    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT, letter_responses=[LetterContent(
        subject="Tokyo", opening="Atterri a Tokyo di sera, il vento sa di sale.",
        moments=[
            {"prose": "la luce bassa di settembre accende le lanterne rosse mentre l'incenso riempie il viale e la folla attraversa piano il tempio antico",
             "place_links": ["https://example.com/poi"]},
            {"prose": "il futon profuma di tatami fresco e la cena di pesce grigliato arriva con il tè caldo mentre fuori la città abbassa le luci",
             "place_links": ["https://example.com/hotel"]},
        ],
        closing="Ne parliamo insieme.")])
    email = FakeEmailSender()
    db = FakeDatabase()

    await _run_with_searches(monkeypatch, llm, email, db, trip, store)

    budgets = [kw["max_tokens"] for kw in llm.calls_kwargs if kw["model"] is LetterContent]
    assert budgets, "compose must call extract for LetterContent"
    assert all(b >= 2048 for b in budgets)


async def test_compose_letter_all_moments_invalid_aborts_without_email(monkeypatch):
    from src.core.models import LetterContent

    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT, responses={LetterContent: LetterContent(
        subject="Creta", opening="Atterri a Heraklion di sera, il vento sa di sale.",
        moments=[
            {"prose": "Una possibile sosta per il van lungo il percorso.",
             "place_links": ["https://example.com/poi"]},
            {"prose": "le mura antiche trattengono il calore del giorno tra pietre chiare e il vento leggero della sera",
             "place_links": ["https://fake.example/castello"]},
        ],
        closing="Ne parliamo insieme.")})
    email = FakeEmailSender()
    db = FakeDatabase()

    await _run_with_searches(monkeypatch, llm, email, db, trip, store)

    assert email.sent == []
    assert db.saved == []
    got = await store.get(trip.id)
    assert got.status == TripStatus.ERROR
    assert "fewer than 2 valid moments" in (got.result or "")
    assert len([p for p, m in llm.calls if m is LetterContent]) == 2


import pytest


@pytest.mark.asyncio
async def test_intercontinental_forces_flights(monkeypatch):
    from src.core.models import ResolvedDestinations, ResolvedPlace

    # LLM decision drives flights: needs_flights=true probes even for van_life
    intent = TripIntent(destination="Patagonia", travel_mode="van_life",
                        needs_flights=True, flight_rationale="Volo per arrivare")
    trip = make_trip(departure_location="Italy", destination="Patagonia")
    store = make_store()
    await store.create(trip)

    flight_called = []

    async def fake_flights(departure, arrival, start_date, end_date, **kwargs):
        flight_called.append((departure, arrival))
        return [{"airline": "ITA", "from": departure, "to": arrival, "departure_date": start_date, "price_eur": 500, "link": "https://example.com/f"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Perito Moreno", "type": "Glacier", "rating": 4.8, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Hotel Patagonia", "price_per_night_eur": 80, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    orchestrator = TripOrchestrator(store=store, llm_client=FakeLLM(response=intent), email_sender=FakeEmailSender(), database=FakeDatabase(), trip_id=trip.id)
    resolved = ResolvedDestinations(destinations=[ResolvedPlace(name="Patagonia", country="Argentina", airport_code="EZE")], rationale="test")
    tool_calls: list[dict] = []
    result = await orchestrator._execute_searches(trip, intent, [], [("2026-09-01", "2026-09-10")], [], tool_calls, resolved=resolved, departure_codes=["MXP"])

    assert flight_called, "flights should be probed when needs_flights=true"
    assert result["geo"]["skipped_flights_reason"] is None
    assert not any(tc.get("skipped") for tc in tool_calls if tc.get("engine") == "google_flights")


@pytest.mark.asyncio
async def test_needs_flights_false_skips_flights(monkeypatch):
    from src.core.models import ResolvedDestinations, ResolvedPlace

    intent = TripIntent(destination="Francia", travel_mode="van_life",
                        needs_flights=False, flight_rationale="Van da casa, niente volo")
    trip = make_trip(departure_location="Italy", destination="Francia")
    store = make_store()
    await store.create(trip)

    flight_called = []

    async def fake_flights(departure, arrival, start_date, end_date, **kwargs):
        flight_called.append((departure, arrival))
        return [{"airline": "AF", "from": departure, "to": arrival, "departure_date": start_date, "price_eur": 100, "link": "https://example.com/f"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Eiffel", "type": "Monument", "rating": 4.6, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Hotel Paris", "price_per_night_eur": 90, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    orchestrator = TripOrchestrator(store=store, llm_client=FakeLLM(response=intent), email_sender=FakeEmailSender(), database=FakeDatabase(), trip_id=trip.id)
    resolved = ResolvedDestinations(destinations=[ResolvedPlace(name="Francia", country="France", airport_code="CDG")], rationale="test")
    tool_calls: list[dict] = []
    result = await orchestrator._execute_searches(trip, intent, [], [("2026-09-01", "2026-09-10")], [], tool_calls, resolved=resolved, departure_codes=["MXP"])

    assert flight_called == [], "flights should be skipped when needs_flights=false"
    assert result["geo"]["skipped_flights_reason"] == "no_flights_needed"
    assert any(tc.get("skipped") and tc.get("reason") == "no_flights_needed" for tc in tool_calls)


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


# --- Task 4 fix round: Jev router flag/fallback coverage ---

class _FakeJevActive:
    """Auto bands on travel_mode/needs_flights; tracks close() calls."""

    def __init__(self):
        self.closed = 0

    async def decide(self, state, questions):
        return {"model": "jev-1.13.0", "answers": {
            "travel_mode": {"value": "van_life", "probability": 0.92},
            "needs_flights": {"value": False, "probability": 0.88},
            "pace": {"value": "rilassato", "probability": 0.9},
            "avoids_crowds": {"value": True, "probability": 0.87},
            "stay_fit": {"value": "van", "probability": 0.91},
            "budget_sensitive": {"value": False, "probability": 0.7},
        }}

    async def close(self):
        self.closed += 1


def _double_fallback_answers():
    return {"model": "jev-1.13.0", "answers": {
        "travel_mode": {"value": "van_life", "probability": 0.1},
        "needs_flights": {"value": True, "probability": 0.2},
        "pace": {"value": "rilassato", "probability": 0.9},
        "avoids_crowds": {"value": True, "probability": 0.87},
        "stay_fit": {"value": "van", "probability": 0.91},
        "budget_sensitive": {"value": False, "probability": 0.7},
    }}


class _FakeJevDoubleFallback:
    async def decide(self, state, questions):
        return _double_fallback_answers()


class _FakeJevError:
    async def decide(self, state, questions):
        from src.services.apis.decisions import JevError
        raise JevError("jev decide failed: TimeoutError: timed out")


class _FakeJevBoom:
    """Non-JevError failure (e.g. malformed payload float() blowup)."""

    async def decide(self, state, questions):
        raise RuntimeError("boom")


async def _run_trip_with_jev(monkeypatch, jev_client):
    """Run a full trip with stubbed searches; build_decision_client patched to jev_client."""
    import src.core.orchestrator as orch

    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT)
    email = FakeEmailSender()
    db = FakeDatabase()

    async def fake_flights(*args, **kwargs):
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01",
                 "price_eur": 320, "link": "https://example.com/flight"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)
    monkeypatch.setattr(orch, "build_decision_client", lambda settings: jev_client)

    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=email,
                                    database=db, trip_id=trip.id)
    await _run(orchestrator)
    got = await store.get(trip.id)
    package = db.saved[0]["package"] if db.saved else None
    return got, email, db, package


def _jev_tool_calls(package):
    return [tc for tc in package["tool_calls"] if tc.get("engine") == "jev-router"]


def test_build_decision_client_none_when_flag_off():
    import asyncio as _asyncio
    from types import SimpleNamespace
    from src.services.apis.decisions import build_decision_client

    off = SimpleNamespace(decision_provider="llm-fallback", typesafe_api_key="secret",
                          decision_model="jev-1.13.0", decision_timeout=5.0)
    assert build_decision_client(off) is None

    no_key = SimpleNamespace(decision_provider="jev", typesafe_api_key="",
                             decision_model="jev-1.13.0", decision_timeout=5.0)
    assert build_decision_client(no_key) is None

    on = SimpleNamespace(decision_provider="jev", typesafe_api_key="secret",
                         decision_model="jev-1.13.0", decision_timeout=5.0)
    client = build_decision_client(on)
    assert client is not None
    _asyncio.run(client.close())


async def test_jev_error_falls_back_to_llm_path(monkeypatch):
    got, email, db, package = await _run_trip_with_jev(monkeypatch, _FakeJevError())
    assert got.status == TripStatus.DONE
    assert len(email.sent) == 1
    assert _jev_tool_calls(package) == []


async def test_jev_generic_error_falls_back_to_llm_path(monkeypatch):
    got, email, db, package = await _run_trip_with_jev(monkeypatch, _FakeJevBoom())
    assert got.status == TripStatus.DONE
    assert len(email.sent) == 1
    assert _jev_tool_calls(package) == []


async def test_double_fallback_bands_use_existing_path(monkeypatch):
    got, email, db, package = await _run_trip_with_jev(monkeypatch, _FakeJevDoubleFallback())
    assert got.status == TripStatus.DONE
    assert len(email.sent) == 1
    assert _jev_tool_calls(package) == []
    assert package["geo"]["skipped_flights_reason"] is None  # LLM intent path probed flights


async def test_flag_off_path_byte_identical(monkeypatch):
    """Default settings (provider llm-fallback) -> build_decision_client returns None,
    existing path runs unchanged: no jev-router entry, research tool_call shapes
    plus the winner revalidation entry only."""
    import src.core.orchestrator as orch
    from src.settings import get_settings

    assert orch.build_decision_client(get_settings()) is None

    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT)
    email = FakeEmailSender()
    db = FakeDatabase()

    async def fake_flights(*args, **kwargs):
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01",
                 "price_eur": 320, "link": "https://example.com/flight"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=email,
                                    database=db, trip_id=trip.id)
    await _run(orchestrator)

    got = await store.get(trip.id)
    assert got.status == TripStatus.DONE
    assert len(email.sent) == 1
    package = db.saved[0]["package"]
    assert _jev_tool_calls(package) == []
    assert all(set(tc) == {"engine", "params", "result_count"} or set(tc) == {"engine", "skipped", "reason"}
               or set(tc) == {"engine", "revalidated", "reason"}  # winner revalidation entry
               for tc in package["tool_calls"])


async def test_jev_active_logs_router_tool_call(monkeypatch):
    jev = _FakeJevActive()
    got, email, db, package = await _run_trip_with_jev(monkeypatch, jev)
    assert got.status == TripStatus.DONE
    assert len(email.sent) == 1
    entries = _jev_tool_calls(package)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["model"] == "jev-1.13.0"
    assert entry["decisions"]["travel_mode"] == "van_life"
    assert set(entry) == {"engine", "model", "decisions", "bands"}
    assert package["geo"]["skipped_flights_reason"] == "no_flights_needed"  # Jev needs_flights=False
    assert jev.closed == 1, "per-call Jev client must be closed after decide"


def test_route_trip_bad_probability_defaults_fallback():
    from src.core.schemas import TripResponse, TripStatus
    from src.core.decision_router import route_trip

    class _BadProb:
        async def decide(self, state, questions):
            return {"model": "jev-1.13.0", "answers": {
                "travel_mode": {"value": "van_life", "probability": "nonsense"},
                "needs_flights": {"value": True, "probability": None},
            }}

    trip = TripResponse(id="t1", status=TripStatus.PENDING, received_at="2026-09-20T00:00:00+00:00",
        email="a@b.it", destination="Creta", departure_location="Italy", free_text="van mare relax")
    out = asyncio.run(route_trip(trip, _BadProb()))
    assert out["bands"]["travel_mode"] == "fallback"
    assert out["bands"]["needs_flights"] == "fallback"
    assert out["decisions"]["travel_mode"] == "van_life"


async def test_decide_http_error_raises_jev_error():
    import httpx
    from src.services.apis.decisions import JevClient, JevError

    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = JevClient(api_key="k", client=http)
        try:
            with pytest.raises(JevError):
                await client.decide({}, {})
        finally:
            await client.close()


async def test_compose_letter_validates_links_and_gates_filler(monkeypatch, caplog):
    import logging

    from src.core.models import LetterContent
    store = make_store()
    trip = await store.create(make_trip())
    letter_first = LetterContent(
        subject="Creta", opening="Atterri a Heraklion di sera, il vento sa di sale.",
        moments=[
            {"prose": "Tra le pietre minoiche la luce di ottobre è bassa e calda, e il dakos sa di orzo e pomodoro.",
             "place_links": ["https://example.com/poi"]},
            {"prose": "Una possibile sosta per il van lungo il percorso.",
             "place_links": ["https://example.com/poi"]},
        ],
        closing="Ne parliamo insieme.")
    letter_retry = LetterContent(
        subject="Creta", opening="Atterri a Heraklion di sera, il vento sa di sale.",
        moments=[
            {"prose": "Tra le pietre minoiche la luce di ottobre è bassa e calda, e il dakos sa di orzo e pomodoro.",
             "place_links": ["https://example.com/poi"]},
            {"prose": "Nel porto vecchio le lampare rientrano all'alba e la bougatsa calda sa di cannella e crema.",
             "place_links": ["https://example.com/hotel"]},
        ],
        closing="Ne parliamo insieme.")
    llm = FakeLLM(response=INTENT, letter_responses=[letter_first, letter_retry])
    email = FakeEmailSender()
    db = FakeDatabase()
    with caplog.at_level(logging.INFO, logger="nostos.orchestrator"):
        await _run_with_searches(monkeypatch, llm, email, db, trip, store)
    assert len(email.sent) == 1
    assert "pietre minoiche" in email.sent[0]["body"]
    assert "https://example.com/poi" in email.sent[0]["body"]
    assert len([p for p, m in llm.calls if m is LetterContent]) == 2
    assert any("letter retry:" in r.getMessage() for r in caplog.records), \
        "a rejected moment must log the specificity retry"
