def test_creta_fixture_email_has_2_phases_no_new_links():
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


async def test_no_flights_email_sent_without_flight_mentions(monkeypatch):
    """SerpAPI voli giù: email comunque inviata, zero frasi su voli mancanti."""
    from tests.fakes import FakeDatabase, FakeLLM, make_store, make_trip
    from tests.test_flight_matrix import EMAIL, _run
    from src.core.models import TripIntent, TripPlan, DayStop
    from src.core.schemas import TripStatus

    trip = make_trip(destination="Creta", departure_location="Italy",
                     start_date="2026-09-01", end_date="2026-09-10",
                     free_text="mare e cibo locale in van")
    intent = TripIntent(destination="Creta", departure_airport_code="MXP",
                        destination_airport_code="HER", travel_mode="van_life",
                        needs_flights=True, flight_rationale="isola")
    plan = TripPlan(days=[DayStop(day_label="G1", poi_refs=[0],
                                  transition="Arrivo e pernottamenti. Non sono disponibili voli curati.")])
    from src.core.models import EmailContent
    email_content = EmailContent(
        subject="Creta", opening="Andiamo.", understanding="Van e mare.",
        resources=[
            {"name": "Taverna X", "description": "cucina locale", "price": "",
             "link": "https://example.com/taverna"},
            {"name": "Campeggio Y", "description": "sosta van", "price": "20 EUR/notte",
             "link": "https://example.com/camp"},
        ],
    )
    llm = FakeLLM(response=intent, email_response=email_content, responses={TripPlan: plan})

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
    assert "voli curati" not in body and "voli curati" not in html
    assert "non sono disponibili voli" not in body


def test_creta_fixture_body_text_has_itinerary_names_only():
    from src.core.orchestrator import TripOrchestrator
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
    body = TripOrchestrator._compose_body_text(content)
    assert "L'itinerario:" in body
    assert "Giorni 1-7 · Heraklion e dintorni" in body
    assert "Giorni 8-15 · Costa sud" in body
    assert "Taverna To Stachi" in body and "Elafonissi" in body and "Campeggio Paleochora" in body
    start = body.index("L'itinerario:")
    block = body[start:]
    end = block.index("\n\n")
    block = block[:end]
    assert "https://" not in block


async def test_compose_email_maps_plan_refs_to_links():
    from src.core.models import DayStop, EmailContent, TripIntent, TripPlan
    from src.core.orchestrator import TripOrchestrator
    from tests.fakes import FakeDatabase, FakeEmailSender, FakeLLM, make_store, make_trip

    curated = {
        "flights": [],
        "maps": [{"name": "Taverna To Stachi", "type": "Restaurant", "rating": 4.8, "address": "", "link": "https://maps.it/t1"}],
        "places": [],
        "rationale": "",
    }
    trip_plan = TripPlan(days=[DayStop(day_label="Giorni 1-7 · Heraklion e dintorni", poi_refs=[0], transition="tappe corte.")])
    email_response = EmailContent(
        subject="Creta",
        opening="o",
        understanding="u",
        resources=[{"name": "Taverna To Stachi", "description": "cucina cretese", "price": "", "link": "https://maps.it/t1"}],
    )
    trip = make_trip()
    llm = FakeLLM(response=TripIntent(destination="Creta"), email_response=email_response)
    orch = TripOrchestrator(store=make_store(), llm_client=llm, email_sender=FakeEmailSender(), database=FakeDatabase(), trip_id=trip.id)
    research = {"corpus": {"flights": [], "maps": list(curated["maps"]), "places": []}, "curated": curated, "trip_plan": trip_plan, "tool_calls": [], "geo": {}}
    content, body_text, body_html, package = await orch._compose_email(trip, TripIntent(destination="Creta"), research)
    assert content["itinerary_days"] == [{"day_label": "Giorni 1-7 · Heraklion e dintorni", "links": ["https://maps.it/t1"], "transition": "tappe corte."}]
    assert "Giorni" in body_html
    assert "Taverna To Stachi" in body_html
