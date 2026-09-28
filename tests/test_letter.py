from src.core.models import LetterContent, LetterMoment


def test_letter_shape():
    letter = LetterContent(
        subject="Creta",
        opening="La porta del van si apre sull'aria salata.",
        moments=[{"prose": "A Festo la luce taglia i muri color miele.",
                  "place_links": ["https://example.com/festo"]}],
        closing="Ne parliamo insieme.",
    )
    assert len(letter.moments) == 1
    assert letter.moments[0].place_links == ["https://example.com/festo"]


def test_letter_prompt_bans_inventory():
    from src.core.models import TripIntent
    from src.core.prompts import build_letter_prompt
    prompt = build_letter_prompt("mare e van", TripIntent(interests=["mare"]), "Festo — https://example.com/festo")
    # NOTE (replaces wrong-shaped tail in brief): the prompt must CITE
    # 'coppia (2)' as a banned bureaucratic format, not omit it.
    assert "coppia (2)" in prompt
    assert "per voi due" in prompt
    assert "possibile sosta" in prompt
    assert "prosa continua" in prompt
    assert "Festo — https://example.com/festo" in prompt


async def test_compose_letter_validates_links_and_moments(monkeypatch):
    from tests.fakes import FakeDatabase, FakeEmailSender, FakeLLM, make_store, make_trip
    from src.core.models import LetterContent, TripIntent
    from src.core.schemas import TripStatus

    store = make_store()
    trip = await store.create(make_trip(destination="Creta"))
    letter = LetterContent(
        subject="Creta",
        opening="La porta del van si apre sull'aria salata.",
        moments=[{"prose": "A Festo la luce taglia i muri color miele e il vento sa di resina.",
                  "place_links": ["https://example.com/festo"]},
                 {"prose": "Il mare della costa sud odora di sale e timo secco al mattino.",
                  "place_links": []}],
        closing="Ne parliamo insieme.")
    llm = FakeLLM(response=TripIntent(destination="Creta"),
                  responses={LetterContent: letter})
    email = FakeEmailSender()
    db = FakeDatabase()

    async def fake_flights(*args, **kwargs):
        return [{"airline": "ANA", "from": "MXP", "to": "HER", "departure_date": "2027-07-30",
                 "price_eur": 320, "link": "https://example.com/flight"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Festo", "type": "sito", "rating": 4.8, "link": "https://example.com/festo"}]

    async def fake_places(**kwargs):
        return [{"name": "Hotel X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    from src.core.orchestrator import TripOrchestrator
    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=email,
                                    database=db, trip_id=trip.id)
    await orchestrator.run()

    got = await store.get(trip.id)
    assert got.status == TripStatus.DONE
    assert len(email.sent) == 1
    body = email.sent[0]["body"]
    assert "Festo" in body
    assert "Punti di partenza" not in body
    assert "L'itinerario" not in body
    assert "Come arrivare" not in body
    package = db.saved[0]["package"]
    assert "dream" not in package
    assert "trip_plan" not in package
    assert package["letter"] == {"moments": 2}
    budgets = [kw["max_tokens"] for (_, m), kw in zip(llm.calls, llm.calls_kwargs) if m is LetterContent]
    assert budgets and all(b >= 2048 for b in budgets)


async def test_compose_letter_all_moments_invalid_aborts_without_email(monkeypatch):
    from tests.fakes import FakeDatabase, FakeEmailSender, FakeLLM, make_store, make_trip
    from src.core.models import LetterContent, TripIntent
    from src.core.schemas import TripStatus

    store = make_store()
    trip = await store.create(make_trip(destination="Creta"))
    bad = LetterContent(
        subject="Creta",
        opening="La porta del van si apre sull'aria salata.",
        moments=[{"prose": "Una possibile sosta per il van lungo il percorso.",
                  "place_links": ["https://example.com/festo"]},
                 {"prose": "Le mura antiche trattengono il calore del giorno tra pietre chiare e il vento leggero della sera.",
                  "place_links": ["https://fake.example/castello"]}],
        closing="Ne parliamo insieme.")
    llm = FakeLLM(response=TripIntent(destination="Creta"),
                  responses={LetterContent: bad})
    email = FakeEmailSender()
    db = FakeDatabase()

    async def fake_flights(*args, **kwargs):
        return [{"airline": "ANA", "from": "MXP", "to": "HER", "departure_date": "2027-07-30",
                 "price_eur": 320, "link": "https://example.com/flight"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Festo", "type": "sito", "rating": 4.8, "link": "https://example.com/festo"}]

    async def fake_places(**kwargs):
        return [{"name": "Hotel X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    from src.core.orchestrator import TripOrchestrator
    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=email,
                                    database=db, trip_id=trip.id)
    await orchestrator.run()

    assert email.sent == []
    assert db.saved == []
    got = await store.get(trip.id)
    assert got.status == TripStatus.ERROR
    assert "fewer than 2 valid moments" in (got.result or "")
    assert len([m for _, m in llm.calls if m is LetterContent]) == 2
