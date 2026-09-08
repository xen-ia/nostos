from urllib.parse import quote_plus

from src.core.orchestrator import _is_junk_link, _maps_search_link


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


def test_maps_search_link_name_and_address():
    assert (
        _maps_search_link("Urquhart Castle", "Loch Ness, UK")
        == "https://www.google.com/maps/search/?api=1&query="
        + quote_plus("Urquhart Castle Loch Ness, UK")
    )
    assert (
        _maps_search_link("Urquhart Castle", "Loch Ness, UK")
        == "https://www.google.com/maps/search/?api=1&query=Urquhart+Castle+Loch+Ness%2C+UK"
    )


def test_maps_search_link_name_only():
    assert (
        _maps_search_link("Urquhart Castle", None)
        == "https://www.google.com/maps/search/?api=1&query=" + quote_plus("Urquhart Castle")
    )
    assert (
        _maps_search_link("Urquhart Castle", "   ")
        == "https://www.google.com/maps/search/?api=1&query=" + quote_plus("Urquhart Castle")
    )


def test_maps_search_link_no_name():
    assert _maps_search_link(None, "Loch Ness, UK") is None
    assert _maps_search_link("", "Loch Ness, UK") is None
    assert _maps_search_link("   ", None) is None


async def test_linkless_maps_item_rescued_with_generated_link(monkeypatch):
    from tests.fakes import FakeDatabase, FakeLLM, make_trip
    from tests.test_flight_matrix import EMAIL, _run
    from src.core.models import TripIntent

    trip = make_trip(start_date="2026-09-01", end_date="2026-09-10")

    async def fake_maps(query, **kwargs):
        return [
            {"name": "Urquhart Castle", "address": "Loch Ness, UK",
             "rating": 4.8, "type": "Attrazione turistica"},
            {"name": "Good POI", "type": "t", "rating": 4.5,
             "link": "https://example.com/poi"},
        ]

    async def fake_flights(*args, **kwargs):
        return []

    async def fake_places(**kwargs):
        return [{"name": "Hotel Generico", "price_per_night_eur": 80,
                 "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)
    intent = TripIntent(destination="Shetland", accommodation_style="hotel")
    db = FakeDatabase()
    await _run(trip, FakeLLM(response=intent, email_response=EMAIL), db)
    corpus_maps = db.saved[0]["package"]["corpus"]["maps"]
    rescued = next(i for i in corpus_maps if i.get("name") == "Urquhart Castle")
    assert "google.com/maps/search" in rescued["link"]
    assert rescued["link"] == (
        "https://www.google.com/maps/search/?api=1&query="
        + quote_plus("Urquhart Castle Loch Ness, UK")
    )
    assert any(i.get("name") == "Good POI" for i in corpus_maps)
