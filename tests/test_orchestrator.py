import pytest

from src.core.models import EmailContent, TripIntent
from src.core.orchestrator import NoResourcesError, TripOrchestrator
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

EMAIL = EmailContent(
    subject="Il tuo viaggio a Tokyo",
    opening="Tokyo in settembre ha un che di magico.",
    understanding="Capisco che cerchi cibo locale lontano dalle folle.",
    resources=[{"name": "Ristorante X", "description": "Ramen", "price": "20 EUR", "link": "https://example.com/x"}],
)


async def _run(orchestrator):
    await orchestrator.run()


def _make_llm():
    return FakeLLM(response=INTENT, email_response=EMAIL)


async def test_happy_path_sends_email_and_saves_history(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = _make_llm()
    email = FakeEmailSender()
    db = FakeDatabase()

    async def fake_flights(*args, **kwargs):
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01", "price_eur": 320, "link": "https://example.com/flight"}]

    async def fake_maps(*args, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(*args, **kwargs):
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

    monkeypatch.setattr("src.core.orchestrator.flights.search", one)
    monkeypatch.setattr("src.core.orchestrator.maps.research", one)
    monkeypatch.setattr("src.core.orchestrator.places.search", one)

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
