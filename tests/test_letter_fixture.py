"""Creta letter fixture: end-to-end letter semantics on a van trip."""


def test_creta_fixture_email_has_2_moments_no_new_links():
    from src.services.apis.email import build_html_email
    resources = [
        {"name": "Volo easyJet · Milano – Heraklion", "description": "", "price": "196 EUR", "link": "https://voli.it/f1"},
        {"name": "Taverna To Stachi", "description": "", "price": "", "link": "https://maps.it/t1"},
        {"name": "Spiaggia Elafonissi", "description": "", "price": "", "link": "https://maps.it/s1"},
        {"name": "Campeggio Paleochora", "description": "", "price": "20 EUR/notte", "link": "https://stay.it/c1"},
    ]
    content = {"opening": "Sbarchi a Heraklion con il van pronto e il mare calmo davanti a te.",
        "resources": resources,
        "sections_map": {"flights": ["https://voli.it/f1"], "places": ["https://stay.it/c1"], "maps": ["https://maps.it/t1", "https://maps.it/s1"]},
        "moments": [
            {"prose": "ritiro van e notti vicino Heraklion tra taverne e vicoli.",
             "place_links": ["https://maps.it/t1"]},
            {"prose": "discesa verso sud tra mare quieto e piazzole ombreggiate.",
             "place_links": ["https://maps.it/s1", "https://stay.it/c1"]},
        ],
        "places": [
            {"name": "Taverna To Stachi", "price": "", "link": "https://maps.it/t1"},
            {"name": "Spiaggia Elafonissi", "price": "", "link": "https://maps.it/s1"},
            {"name": "Campeggio Paleochora", "price": "20 EUR/notte", "link": "https://stay.it/c1"},
            {"name": "Volo easyJet · Milano – Heraklion", "price": "196 EUR", "link": "https://voli.it/f1"},
        ],
        "closing": "Ne parliamo insieme.",
        "appendix": {"groups": [], "source_links": []}, "cta": "c", "honest_note": "n",
        "travel_mode": "van_life", "mobility": [], "accommodation_style": "van", "feedback_link": ""}
    html = build_html_email(content)
    assert html.index("Sbarchi a Heraklion") < html.index("ritiro van") < html.index("discesa verso sud")
    assert html.index("discesa verso sud") < html.index("I luoghi")
    assert "L'itinerario" not in html  # phases gone with the letter template
    assert '<table class="card-frame"' not in html
    assert "https://voli.it/f1" in html


async def test_no_flights_email_sent_without_flight_mentions(monkeypatch):
    """SerpAPI voli giù: email comunque inviata, zero frasi su voli mancanti."""
    from tests.fakes import FakeDatabase, FakeLLM, make_store, make_trip
    from src.core.models import LetterContent, TripIntent
    from src.core.schemas import TripStatus

    trip = make_trip(destination="Creta", departure_location="Italy",
                     start_date="2026-09-01", end_date="2026-09-10",
                     free_text="mare e cibo locale in van")
    intent = TripIntent(destination="Creta", departure_airport_code="MXP",
                        destination_airport_code="HER", travel_mode="van_life",
                        needs_flights=True, flight_rationale="isola")
    letter = LetterContent(
        subject="Creta",
        opening="Sbarchi a Creta con il van pronto e il mare calmo davanti a te.",
        moments=[
            {"prose": "la taverna serve cucina locale tra tavoli di legno e profumo di origano mentre il sole cala sul mare vicino",
             "place_links": ["https://example.com/taverna"]},
            {"prose": "il campeggio offre una sosta tranquilla per il van tra ulivi e piazzole ombreggiate con il mare a due passi",
             "place_links": ["https://example.com/camp"]},
        ],
        closing="Ne parliamo insieme.",
    )
    llm = FakeLLM(response=intent, letter_responses=[letter])

    async def dead_flights(*args, **kwargs):
        raise RuntimeError("serpapi down")

    async def fake_maps(query, **kwargs):
        return [{"name": "Taverna X", "type": "restaurant", "rating": 4.8,
                 "link": "https://example.com/taverna"}]

    async def fake_places(**kwargs):
        return [{"name": "Campeggio Y", "price_per_night_eur": 20,
                 "link": "https://example.com/camp"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", dead_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)
    from tests.fakes import FakeEmailSender
    store = make_store()
    trip = await store.create(trip)
    email = FakeEmailSender()
    db = FakeDatabase()
    from src.core.orchestrator import TripOrchestrator
    orch = TripOrchestrator(store=store, llm_client=llm, email_sender=email,
                            database=db, trip_id=trip.id)
    await orch.run()

    got = await store.get(trip.id)
    assert got.status == TripStatus.DONE
    assert len(email.sent) == 1
    body = email.sent[0]["body"] or ""
    html = email.sent[0]["html"] or ""
    assert "Taverna X" in body
    assert "voli curati" not in body and "voli curati" not in html
    assert "non sono disponibili voli" not in body


def test_creta_fixture_body_text_mirrors_letter_in_order():
    from src.core.orchestrator import TripOrchestrator
    resources = [
        {"name": "Volo easyJet · Milano – Heraklion", "description": "", "price": "196 EUR", "link": "https://voli.it/f1"},
        {"name": "Taverna To Stachi", "description": "", "price": "", "link": "https://maps.it/t1"},
        {"name": "Spiaggia Elafonissi", "description": "", "price": "", "link": "https://maps.it/s1"},
        {"name": "Campeggio Paleochora", "description": "", "price": "20 EUR/notte", "link": "https://stay.it/c1"},
    ]
    content = {"opening": "Sbarchi a Heraklion con il van pronto.",
        "resources": resources,
        "sections_map": {"flights": ["https://voli.it/f1"], "places": ["https://stay.it/c1"], "maps": ["https://maps.it/t1", "https://maps.it/s1"]},
        "moments": [
            {"prose": "ritiro van e notti vicino Heraklion.",
             "place_links": ["https://maps.it/t1"]},
            {"prose": "discesa verso sud tra mare quieto.",
             "place_links": ["https://maps.it/s1", "https://stay.it/c1"]},
        ],
        "places": [
            {"name": "Taverna To Stachi", "price": "", "link": "https://maps.it/t1"},
            {"name": "Spiaggia Elafonissi", "price": "", "link": "https://maps.it/s1"},
            {"name": "Campeggio Paleochora", "price": "20 EUR/notte", "link": "https://stay.it/c1"},
            {"name": "Volo easyJet · Milano – Heraklion", "price": "196 EUR", "link": "https://voli.it/f1"},
        ],
        "closing": "Ne parliamo insieme.",
        "appendix": {"groups": [], "source_links": []}, "cta": "c", "honest_note": "n",
        "travel_mode": "van_life", "mobility": [], "accommodation_style": "van", "feedback_link": ""}
    body = TripOrchestrator._compose_body_text(content)
    order = ["Sbarchi a Heraklion", "ritiro van", "https://maps.it/t1",
             "discesa verso sud", "https://maps.it/s1", "https://stay.it/c1",
             "I luoghi:", "Taverna To Stachi", "Volo easyJet · Milano"]
    positions = [body.index(s) for s in order]
    assert positions == sorted(positions), "twin strings must follow HTML order"
    assert "L'itinerario:" not in body  # phases gone with the letter template
    for link in ("https://maps.it/t1", "https://maps.it/s1", "https://stay.it/c1"):
        assert body.count(link) == 2  # twin: once in its moment, once in "I luoghi"
    assert body.count("https://voli.it/f1") == 1  # flight uncited: places list only


async def test_compose_letter_builds_resources_from_curated():
    """LOAD-BEARING: the letter path renders no links unless content['resources']
    is populated deterministically from curated research (never LLM prose)."""
    from src.core.models import LetterContent, TripIntent
    from src.core.orchestrator import TripOrchestrator
    from tests.fakes import FakeDatabase, FakeEmailSender, FakeLLM, make_store, make_trip

    curated = {
        "flights": [{"airline": "easyJet", "from": "Milano", "to": "Heraklion",
                     "departure_date": "2026-09-01", "price_eur": 196, "link": "https://voli.it/f1"}],
        "maps": [{"name": "Taverna To Stachi", "type": "Restaurant", "rating": 4.8,
                  "address": "", "link": "https://maps.it/t1"}],
        "places": [{"name": "Campeggio Paleochora", "price_per_night_eur": 20,
                    "link": "https://stay.it/c1"}],
        "rationale": "",
    }
    letter = LetterContent(
        subject="Creta",
        opening="Sbarchi a Heraklion con il van pronto e il mare calmo davanti a te.",
        moments=[
            {"prose": "la taverna serve cucina locale tra tavoli di legno mentre il sole cala piano sul mare vicino",
             "place_links": ["https://maps.it/t1"]},
            {"prose": "il campeggio accoglie il van tra ulivi e piazzole ombreggiate con il mare a due passi",
             "place_links": ["https://stay.it/c1"]},
        ],
        closing="Ne parliamo insieme.",
    )
    trip = make_trip()
    llm = FakeLLM(response=TripIntent(destination="Creta"), letter_responses=[letter])
    orch = TripOrchestrator(store=make_store(), llm_client=llm, email_sender=FakeEmailSender(),
                            database=FakeDatabase(), trip_id=trip.id)
    research = {"corpus": {"flights": list(curated["flights"]), "maps": list(curated["maps"]),
                           "places": list(curated["places"])},
                "curated": curated, "tool_calls": [], "geo": {}}
    content, body_text, body_html, package = await orch._compose_letter(
        trip, TripIntent(destination="Creta"), research)
    links = [r["link"] for r in content["resources"]]
    assert links == ["https://voli.it/f1", "https://maps.it/t1", "https://stay.it/c1"]
    assert "taverna serve cucina locale" in body_html and "campeggio accoglie il van" in body_html
    assert "taverna serve cucina locale" in body_text and "campeggio accoglie il van" in body_text
    for link in links:
        assert link in body_html and link in body_text  # twin: no lost links


async def test_compose_letter_sets_trip_summary():
    """REGRESSION: letter mail must render the trip-memory slot (destination + dates)."""
    from src.core.models import LetterContent, TripIntent
    from src.core.orchestrator import TripOrchestrator
    from src.services.apis.email import format_trip_summary
    from tests.fakes import FakeDatabase, FakeEmailSender, FakeLLM, make_store, make_trip

    curated = {
        "flights": [{"airline": "easyJet", "from": "Milano", "to": "Heraklion",
                     "departure_date": "2026-09-01", "price_eur": 196, "link": "https://voli.it/f1"}],
        "maps": [{"name": "Taverna To Stachi", "type": "Restaurant", "rating": 4.8,
                  "address": "", "link": "https://maps.it/t1"}],
        "places": [{"name": "Campeggio Paleochora", "price_per_night_eur": 20,
                    "link": "https://stay.it/c1"}],
        "rationale": "",
    }
    letter = LetterContent(
        subject="Creta",
        opening="Sbarchi a Heraklion con il van pronto e il mare calmo davanti a te.",
        moments=[
            {"prose": "la taverna serve cucina locale tra tavoli di legno mentre il sole cala piano sul mare vicino",
             "place_links": ["https://maps.it/t1"]},
            {"prose": "il campeggio accoglie il van tra ulivi e piazzole ombreggiate con il mare a due passi",
             "place_links": ["https://stay.it/c1"]},
        ],
        closing="Ne parliamo insieme.",
    )
    trip = make_trip(destination="Creta", start_date="2026-09-01", end_date="2026-09-10",
                     travelers_count=2, travelers_type="coppia")
    llm = FakeLLM(response=TripIntent(destination="Creta"), letter_responses=[letter])
    orch = TripOrchestrator(store=make_store(), llm_client=llm, email_sender=FakeEmailSender(),
                            database=FakeDatabase(), trip_id=trip.id)
    research = {"corpus": {"flights": list(curated["flights"]), "maps": list(curated["maps"]),
                           "places": list(curated["places"])},
                "curated": curated, "tool_calls": [], "geo": {}}
    content, _body_text, body_html, _package = await orch._compose_letter(
        trip, TripIntent(destination="Creta"), research)
    expected = format_trip_summary("Creta", "2026-09-01", "2026-09-10", 2, "coppia")
    assert content["trip_summary"] == expected
    assert "Creta" in body_html and "1 set" in body_html and "10 set" in body_html
    assert expected in body_html
