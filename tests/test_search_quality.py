"""Search-quality behaviors: language, floor/sort, anchor retry, budget sort, Jev scoring, cache."""
from src.services.tools.language import language_name, search_language


def test_search_language_per_destination():
    assert search_language(["Camerun"]) == "fr"
    assert search_language(["Italia"]) == "it"
    assert search_language(["Giappone"]) == "en"
    assert search_language([]) == "en"
    assert search_language(["Cameroun", "Italy"]) == "fr"
    assert language_name("fr") == "French"


async def test_maps_floor_drops_low_rated(monkeypatch):
    from src.core.models import TripIntent
    from src.core.orchestrator import TripOrchestrator
    from tests.fakes import FakeDatabase, FakeEmailSender, FakeLLM, make_store, make_trip

    async def fake_maps(query, **kwargs):
        return [
            {"name": "Trappola", "type": "t", "rating": 2.1, "link": "https://example.com/bad"},
            {"name": "Bello", "type": "t", "rating": 4.8, "link": "https://example.com/poi"},
        ]

    async def fake_flights(*a, **k):
        return []

    async def fake_places(**kwargs):
        return [{"name": "Hotel", "price_per_night_eur": 80, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)
    store = make_store()
    trip = await store.create(make_trip(destination="X"))
    db = FakeDatabase()
    orch_obj = TripOrchestrator(store=store, llm_client=FakeLLM(response=TripIntent(destination="X")),
                                email_sender=FakeEmailSender(), database=db, trip_id=trip.id)
    await orch_obj.run()
    names = [i["name"] for i in db.saved[0]["package"]["corpus"]["maps"]]
    assert "Bello" in names and "Trappola" not in names


def test_jev_scoring_reranks_corpus():
    import asyncio
    from src.core.orchestrator import TripOrchestrator

    from tests.fakes import make_trip
    async def go():
        orch = TripOrchestrator.__new__(TripOrchestrator)
        trip = make_trip(destination="X")

        class FakeJev:
            async def decide(self, state, questions):
                assert set(questions) == {"fit_0", "fit_1"}
                return {"model": "m", "answers": {
                    "fit_0": {"type": "noul", "noul": 0.1},
                    "fit_1": {"type": "noul", "noul": 0.9}}}

            async def close(self):
                pass

        research = {"corpus": {
            "flights": [],
            "maps": [{"name": "A", "link": "https://a.example"},
                     {"name": "B", "link": "https://b.example"}],
            "places": []}, "tool_calls": []}
        await orch._apply_jev_scores(FakeJev(), trip, research, {})
        assert [i["link"] for i in research["corpus"]["maps"]] == [
            "https://b.example", "https://a.example"]
        assert research["tool_calls"][-1]["engine"] == "jev-scorer"

    asyncio.run(go())


def test_jev_scoring_fail_open():
    import asyncio
    from src.core.orchestrator import TripOrchestrator
    from tests.fakes import make_trip

    async def go():
        orch = TripOrchestrator.__new__(TripOrchestrator)
        trip = make_trip(destination="X")

        class BoomJev:
            async def decide(self, state, questions):
                raise RuntimeError("down")

        research = {"corpus": {
            "flights": [],
            "maps": [{"name": "A", "link": "https://a.example"}],
            "places": []}, "tool_calls": []}
        await orch._apply_jev_scores(BoomJev(), trip, research, {})
        assert [i["link"] for i in research["corpus"]["maps"]] == ["https://a.example"]

    asyncio.run(go())


def test_cache_key_stable_and_ttl_per_engine():
    from src.services.apis.serpapi import ENGINE_CACHE_TTL, _cache_key

    p1 = {"engine": "google_maps", "q": "x", "api_key": "SECRET"}
    p2 = {"engine": "google_maps", "q": "x", "api_key": "OTHER"}
    assert _cache_key(p1) == _cache_key(p2)
    assert _cache_key({"engine": "google_maps", "q": "y"}) != _cache_key(p1)
    assert ENGINE_CACHE_TTL["google_maps"] == 7 * 86400
    assert ENGINE_CACHE_TTL["google_flights"] < ENGINE_CACHE_TTL["google_maps"]


def test_cache_hit_skips_fetch():
    import asyncio
    import fakeredis.aioredis
    import src.services.apis.serpapi as serp

    async def go():
        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        serp._cache_redis = fake
        try:
            params = {"engine": "google_maps", "q": "cache-test-xyz"}

            class Resp:
                def as_dict(self):
                    return {"local_results": [{"title": "Cached"}]}

            class FakeClient:
                def __init__(self):
                    self.calls = 0

                def search(self, p):
                    self.calls += 1
                    return Resp()

            client = FakeClient()
            first = await serp.search(params, timeout=5.0, api_key="k", client=client)
            second = await serp.search(params, timeout=5.0, api_key="k", client=client)
            assert first == second == {"local_results": [{"title": "Cached"}]}
            assert client.calls == 1
        finally:
            serp._cache_redis = None

    asyncio.run(go())


async def test_empty_targeted_query_retries_anchor(monkeypatch):
    from src.core.models import TargetQueries, TripIntent
    from src.core.orchestrator import TripOrchestrator
    from tests.fakes import FakeDatabase, FakeEmailSender, FakeLLM, make_store, make_trip

    from src.core.models import LetterContent

    async def fake_maps(query, **kwargs):
        if query.startswith("Anchor"):
            return [{"name": "Rescued", "type": "t", "rating": 4.5, "link": "https://example.com/r"}]
        if query.startswith("Over specific"):
            return []
        return [{"name": "AnchorPlace", "type": "t", "rating": 4.5, "link": "https://example.com/a"}]

    async def fake_flights(*a, **k):
        return []

    async def fake_places(**kwargs):
        return [{"name": "Hotel", "price_per_night_eur": 80, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)
    store = make_store()
    trip = await store.create(make_trip(destination="X"))
    llm = FakeLLM(
        response=TripIntent(destination="X"),
        responses={TargetQueries: TargetQueries(queries=[
            {"query": "Over specific query with zero results", "based_on": "Anchor place"}])},
        letter_responses=[LetterContent(
            subject="X", opening="Si parte.",
            moments=[
                {"prose": "La piazzetta di AnchorPlace profuma di gelsomino mentre le persiane sbattono piano nel vento del pomeriggio.",
                 "place_links": ["https://example.com/a"]},
                {"prose": "A Rescued la luce del mattino entra dalle finestre alte e il pavimento fresco invita a sostare.",
                 "place_links": ["https://example.com/r"]}],
            closing="Ne parliamo.")],
    )
    db = FakeDatabase()
    orch_obj = TripOrchestrator(store=store, llm_client=llm, email_sender=FakeEmailSender(),
                                database=db, trip_id=trip.id)
    await orch_obj.run()
    names = [i["name"] for i in db.saved[0]["package"]["corpus"]["maps"]]
    assert "Rescued" in names


async def test_budget_trip_sorts_stays_ascending(monkeypatch):
    from src.core.models import TripIntent
    from src.core.orchestrator import TripOrchestrator
    from tests.fakes import FakeDatabase, FakeEmailSender, FakeLLM, make_store, make_trip

    async def fake_maps(query, **kwargs):
        return [{"name": "POI", "type": "t", "rating": 4.5, "link": "https://example.com/poi"}]

    async def fake_flights(*a, **k):
        return []

    async def fake_places(**kwargs):
        return [{"name": "Caro", "price_per_night_eur": 300, "link": "https://example.com/caro"},
                {"name": "Base", "price_per_night_eur": 60, "link": "https://example.com/base"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)
    store = make_store()
    trip = await store.create(make_trip(destination="X"))
    db = FakeDatabase()
    from src.core.models import LetterContent
    llm = FakeLLM(
        response=TripIntent(destination="X", budget_sensitive=True),
        letter_responses=[LetterContent(
            subject="X", opening="Si parte.",
            moments=[
                {"prose": "La piazzetta principale profuma di gelsomino mentre le persiane sbattono piano nel vento caldo del pomeriggio estivo.",
                 "place_links": ["https://example.com/poi"]},
                {"prose": "La hall silenziosa accoglie con marmi freschi e luci basse della sera tra poltrone di velluto.",
                 "place_links": ["https://example.com/base"]}],
            closing="Ne parliamo.")],
    )
    orch_obj = TripOrchestrator(
        store=store, llm_client=llm,
        email_sender=FakeEmailSender(), database=db, trip_id=trip.id)
    await orch_obj.run()
    names = [i["name"] for i in db.saved[0]["package"]["corpus"]["places"]]
    assert names.index("Base") < names.index("Caro")
