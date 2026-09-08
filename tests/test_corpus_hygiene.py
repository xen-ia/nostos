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


async def test_places_retry_without_destination_uses_bare_hotels(monkeypatch):
    from tests.fakes import FakeDatabase, FakeLLM, make_trip
    from tests.test_flight_matrix import EMAIL, _run
    from src.core.models import TripIntent

    trip = make_trip(destination=None, start_date="2026-09-01", end_date="2026-09-10")
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
    intent = TripIntent(destination=None, accommodation_style="hotel")
    db = FakeDatabase()
    await _run(trip, FakeLLM(response=intent, email_response=EMAIL), db)
    assert len(queries) == 2
    assert queries[1] == "hotels"
