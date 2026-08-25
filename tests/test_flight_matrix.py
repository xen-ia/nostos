"""Flight matrix + geo planning behaviors (spec Part C1-C4)."""
import logging

from src.core.models import (
    DepartureAirports,
    EmailContent,
    ResolvedDestinations,
    ResolvedPlace,
    TripIntent,
)
from src.core.orchestrator import TripOrchestrator
from src.core.schemas import TripStatus
from tests.fakes import FakeDatabase, FakeEmailSender, FakeLLM, make_store, make_trip

INTENT = TripIntent(
    destination="Caraibi",
    departure_airport_code="MXP",
    destination_airport_code="HND",
    interests=["mare"],
    style=["autentico"],
)

EMAIL = EmailContent(
    subject="Il tuo viaggio",
    opening="Partiamo.",
    understanding="Capisco che cerchi mare lontano dalle folle.",
    resources=[{"name": "POI", "description": "", "price": "", "link": "https://example.com/poi"}],
)


def _make_llm(resolved=None, departures=None):
    responses = {}
    if resolved is not None:
        responses[ResolvedDestinations] = resolved
    if departures is not None:
        responses[DepartureAirports] = departures
    return FakeLLM(response=INTENT, email_response=EMAIL, responses=responses)


def _patch_searches(monkeypatch, *, flights_fn=None, maps_fn=None, places_fn=None):
    async def default_flights(*args, **kwargs):
        return [{"airline": "A", "from": args[0], "to": args[1], "departure_date": args[2],
                 "price_eur": 100, "link": "https://example.com/f"}]

    async def default_maps(query, **kwargs):
        return [{"name": "POI", "type": "t", "rating": 4.5, "link": "https://example.com/poi"}]

    async def default_places(**kwargs):
        return [{"name": "Hotel X", "price_per_night_eur": 90, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", flights_fn or default_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", maps_fn or default_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", places_fn or default_places)


async def _run(monkeypatched_trip, llm, db):
    store = make_store()
    trip = await store.create(monkeypatched_trip)
    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=FakeEmailSender(),
                                    database=db, trip_id=trip.id)
    await orchestrator.run()
    return store


# --- C1/C2: RESOLVE + departure expansion steer every downstream query ---


async def test_region_trip_resolves_destination_and_logs_rationale(monkeypatch):
    trip = make_trip(
        destination="Caraibi",
        start_date="2026-12-01",
        end_date="2026-12-10",
        free_text="mare e relax lontano dalle folle",
    )
    llm = _make_llm(
        resolved=ResolvedDestinations(
            destinations=[
                ResolvedPlace(name="Santa Lucia", country="Cuba", airport_code="UVF"),
                ResolvedPlace(name="Dominicus", country="Repubblica Dominicana", airport_code="SDQ"),
            ],
            rationale="Mare tranquillo e ritmo lento come richiesto",
        ),
        departures=DepartureAirports(codes=["MXP", "FCO"]),
    )

    explore_queries = []
    place_queries = []
    flight_args = []

    async def fake_maps(query, **kwargs):
        explore_queries.append(query)
        return [{"name": "POI", "type": "t", "rating": 4.5, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        place_queries.append(kwargs.get("query"))
        return [{"name": "Hotel X", "price_per_night_eur": 90, "link": "https://example.com/hotel"}]

    async def fake_flights(*args, **kwargs):
        flight_args.append(args)
        return [{"airline": "A", "from": args[0], "to": args[1], "departure_date": args[2],
                 "price_eur": 100, "link": f"https://example.com/f/{args[0]}{args[1]}"}]

    _patch_searches(monkeypatch, flights_fn=fake_flights, maps_fn=fake_maps, places_fn=fake_places)
    db = FakeDatabase()
    await _run(trip, llm, db)

    assert any("Santa Lucia" in q for q in explore_queries), "explore must target resolved names"
    assert place_queries[-1] == "hotels in Santa Lucia e Dominicus"

    assert flight_args, "resolved arrival codes must enable probes"
    assert {a[0] for a in flight_args} == {"MXP", "FCO"}
    assert {a[1] for a in flight_args} <= {"UVF", "SDQ"}

    package = db.saved[0]["package"]
    assert [p["name"] for p in package["geo"]["resolved"]] == ["Santa Lucia", "Dominicus"]
    assert package["geo"]["departure_codes"] == ["MXP", "FCO"]
    assert package["geo"]["skipped_flights_reason"] is None

    email_prompts = [p for p, m in llm.calls if m is EmailContent]
    assert email_prompts and "Focus scelto dal sistema: Mare tranquillo" in email_prompts[0]


async def test_stay_preference_steers_places_query(monkeypatch):
    trip = make_trip(start_date="2026-09-01", end_date="2026-09-10", stay_preference="agriturismo")
    place_queries = []

    async def fake_places(**kwargs):
        place_queries.append(kwargs.get("query"))
        return [{"name": "Agriturismo Y", "price_per_night_eur": 80, "link": "https://example.com/h"}]

    _patch_searches(monkeypatch, places_fn=fake_places)
    await _run(trip, _make_llm(), FakeDatabase())

    assert place_queries[-1] == "agriturismo stays in Caraibi"


# --- C3 gate: travel_mode blocks all flight probes ---


async def test_van_trip_skips_all_flight_probes(monkeypatch):
    trip = make_trip(start_date="2026-09-01", end_date="2026-09-10", travel_mode="van")
    calls = []

    async def fake_flights(*args, **kwargs):
        calls.append(args)
        return []

    _patch_searches(monkeypatch, flights_fn=fake_flights)
    db = FakeDatabase()
    await _run(trip, _make_llm(), db)

    assert calls == [], "travel_mode van must execute zero probes"
    skips = [tc for tc in db.saved[0]["package"]["tool_calls"] if tc.get("engine") == "google_flights"]
    assert skips == [{"engine": "google_flights", "skipped": True, "reason": "travel_mode:van"}]
    assert db.saved[0]["package"]["geo"]["skipped_flights_reason"] == "travel_mode:van"


async def test_missing_airports_after_geo_planning_skips_probes(monkeypatch):
    trip = make_trip(
        destination=None, departure_location=None,
        start_date="2026-09-01", end_date="2026-09-10",
    )
    intent = TripIntent(destination=None)
    llm = FakeLLM(response=intent, email_response=EMAIL)  # geo defaults: no resolutions, no codes
    calls = []

    async def fake_flights(*args, **kwargs):
        calls.append(args)
        return []

    async def fake_places(**kwargs):
        return [{"name": "POI", "price_per_night_eur": 90, "link": "https://example.com/poi"}]

    _patch_searches(monkeypatch, flights_fn=fake_flights, places_fn=fake_places)
    db = FakeDatabase()
    await _run(trip, llm, db)

    assert calls == [], "raw strings must never reach google_flights"
    skips = [tc for tc in db.saved[0]["package"]["tool_calls"] if tc.get("engine") == "google_flights"]
    assert skips == [{"engine": "google_flights", "skipped": True, "reason": "no_airports"}]


async def test_empty_departure_codes_with_resolved_arrivals_skip_probes(monkeypatch):
    trip = make_trip(start_date="2026-09-01", end_date="2026-09-10")
    intent = TripIntent(
        destination="Caraibi",
        departure_airport_code=None,
        destination_airport_code=None,
    )
    llm = FakeLLM(
        response=intent,
        email_response=EMAIL,
        responses={
            ResolvedDestinations: ResolvedDestinations(
                destinations=[ResolvedPlace(name="Santa Lucia", country="Cuba", airport_code="UVF")],
                rationale="Mare tranquillo",
            ),
            DepartureAirports: DepartureAirports(codes=[]),
        },
    )
    calls = []

    async def fake_flights(*args, **kwargs):
        calls.append(args)
        return []

    _patch_searches(monkeypatch, flights_fn=fake_flights)
    db = FakeDatabase()
    await _run(trip, llm, db)

    assert calls == [], "empty departure side must produce zero probes"
    package = db.saved[0]["package"]
    skips = [tc for tc in package["tool_calls"] if tc.get("engine") == "google_flights"]
    assert skips == [{"engine": "google_flights", "skipped": True, "reason": "no_airports"}]
    assert package["geo"]["skipped_flights_reason"] == "no_airports"


# --- C3 windows: hard vs flexible vs absent dates ---


async def test_hard_dates_probe_exactly_one_window(monkeypatch):
    trip = make_trip(start_date="2026-09-01", end_date="2026-09-10")  # flexible_dates=False
    starts = []

    async def fake_flights(*args, **kwargs):
        starts.append(args[2])
        return [{"airline": "A", "from": args[0], "to": args[1], "departure_date": args[2],
                 "price_eur": 100, "link": "https://example.com/f"}]

    _patch_searches(monkeypatch, flights_fn=fake_flights)
    await _run(trip, _make_llm(), FakeDatabase())

    assert starts == ["2026-09-01"]


async def test_flexible_dates_probe_three_deduped_windows(monkeypatch):
    trip = make_trip(start_date="2026-09-01", end_date="2026-09-10", flexible_dates=True)
    combos = []

    async def fake_flights(*args, **kwargs):
        combos.append((args[2], args[3]))
        return [{"airline": "A", "from": args[0], "to": args[1], "departure_date": args[2],
                 "price_eur": 100, "link": "https://example.com/f"}]

    _patch_searches(monkeypatch, flights_fn=fake_flights)
    await _run(trip, _make_llm(), FakeDatabase())

    assert sorted(combos) == [("2026-08-25", "2026-09-03"),
                              ("2026-09-01", "2026-09-10"),
                              ("2026-09-08", "2026-09-17")]


async def test_absent_dates_still_use_period_plan_windows(monkeypatch):
    from src.core.models import PeriodPlan

    trip = make_trip(start_date=None, end_date=None)
    llm = FakeLLM(
        response=INTENT,
        email_response=EMAIL,
        responses={PeriodPlan: PeriodPlan(windows=[
            {"start": "2026-09-01", "end": "2026-09-15"},
            {"start": "2026-10-01", "end": "2026-10-15"},
        ])},
    )
    starts = []

    async def fake_flights(*args, **kwargs):
        starts.append(args[2])
        return [{"airline": "A", "from": args[0], "to": args[1], "departure_date": args[2],
                 "price_eur": 100, "link": "https://example.com/f"}]

    _patch_searches(monkeypatch, flights_fn=fake_flights)
    await _run(trip, llm, FakeDatabase())

    assert sorted(starts) == ["2026-09-01", "2026-10-01"]


# --- C3 cap: MAX_FLIGHT_PROBES with windows -> arrivals -> departures priority ---


async def test_cap_keeps_eight_probes_covering_all_windows_first(monkeypatch):
    trip = make_trip(start_date="2026-09-01", end_date="2026-09-10", flexible_dates=True)
    llm = _make_llm(
        resolved=ResolvedDestinations(destinations=[
            ResolvedPlace(name="Alpha", airport_code="AAA"),
            ResolvedPlace(name="Beta", airport_code="BBB"),
        ]),
        departures=DepartureAirports(codes=["MXP", "LIN", "BGY"]),  # 3x2 arrivals... 3 dep x 2 arr x 3 win = 18
    )
    combos = []

    async def fake_flights(*args, **kwargs):
        combos.append((args[0], args[1], args[2]))
        return [{"airline": "A", "from": args[0], "to": args[1], "departure_date": args[2],
                 "price_eur": 100, "link": "https://example.com/f"}]

    _patch_searches(monkeypatch, flights_fn=fake_flights)
    await _run(trip, llm, FakeDatabase())

    assert len(combos) == 8
    # priority: every window covered with the narrowest pair first, then extra arrivals
    # (BBB), then extra departures (LIN) — never extra departures before all windows.
    expected = [
        ("MXP", "AAA", "2026-09-01"), ("MXP", "AAA", "2026-08-25"), ("MXP", "AAA", "2026-09-08"),
        ("MXP", "BBB", "2026-09-01"), ("MXP", "BBB", "2026-08-25"), ("MXP", "BBB", "2026-09-08"),
        ("LIN", "AAA", "2026-09-01"), ("LIN", "AAA", "2026-08-25"),
    ]
    assert combos == expected


# --- C4: maps corpus drops link-less entries ---


async def test_maps_linkless_entries_dropped_and_logged(monkeypatch, caplog):
    trip = make_trip(start_date="2026-09-01", end_date="2026-09-10")

    async def fake_maps(query, **kwargs):
        return [
            {"name": "Junk No Link", "type": "t", "rating": None},
            {"name": "Good POI", "type": "t", "rating": 4.5, "link": "https://example.com/poi"},
        ]

    _patch_searches(monkeypatch, maps_fn=fake_maps)
    db = FakeDatabase()
    with caplog.at_level(logging.WARNING, logger="nostos.orchestrator"):
        await _run(trip, _make_llm(), db)

    corpus_maps = db.saved[0]["package"]["corpus"]["maps"]
    assert [i["name"] for i in corpus_maps] == ["Good POI"]
    assert any("link-less" in r.getMessage() and "Junk No Link" in r.getMessage() for r in caplog.records)


# --- winner selection across probes ---


async def test_cheapest_flight_across_windows_wins(monkeypatch):
    from src.core.models import PeriodPlan

    trip = make_trip(start_date=None, end_date=None)
    llm = FakeLLM(
        response=INTENT,
        email_response=EMAIL,
        responses={PeriodPlan: PeriodPlan(windows=[
            {"start": "2026-09-01", "end": "2026-09-15"},
            {"start": "2026-10-01", "end": "2026-10-15"},
        ])},
    )

    async def fake_flights(*args, **kwargs):
        price = 400 if args[2] == "2026-09-01" else 300
        return [{"airline": "A", "from": args[0], "to": args[1], "departure_date": args[2],
                 "price_eur": price, "link": f"https://example.com/f/{args[2]}"}]

    seen_check_in = []
    async def fake_places(**kwargs):
        seen_check_in.append(kwargs.get("check_in_date"))
        return [{"name": "Hotel X", "price_per_night_eur": 90, "link": "https://example.com/hotel"}]

    _patch_searches(monkeypatch, flights_fn=fake_flights, places_fn=fake_places)
    db = FakeDatabase()
    await _run(trip, llm, db)

    package = db.saved[0]["package"]
    assert len(package["corpus"]["flights"]) == 1
    assert package["corpus"]["flights"][0]["price_eur"] == 300
    assert seen_check_in[-1] == "2026-10-01"  # stays aligned to cheapest winning window
