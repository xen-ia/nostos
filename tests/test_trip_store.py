import pytest

from src.core.schemas import TripStatus
from src.services.trip_store import TripNotFoundError
from tests.fakes import make_store, make_trip


async def test_create_get_roundtrip():
    store = make_store()
    trip = await store.create(make_trip())
    got = await store.get(trip.id)

    assert got.id == trip.id
    assert got.email == "test@example.com"
    assert got.destination == "Tokyo"
    assert got.start_date == "2026-09-01"
    assert got.end_date == "2026-09-10"
    assert got.travelers_count == 2
    assert got.travelers_type == "coppia"
    assert got.budget_range == "medio"
    assert got.departure_location == "MXP"
    assert got.status == TripStatus.PENDING


async def test_create_get_roundtrip_structured_inputs():
    store = make_store()
    trip = await store.create(
        make_trip(
            travelers_composition="3 adulti, 2 bambini (6 e 9 anni)",
            budget_amount="max 1500 EUR a persona",
            travel_mode="van",
            stay_preference="agriturismo",
        )
    )
    got = await store.get(trip.id)

    assert got.travelers_composition == "3 adulti, 2 bambini (6 e 9 anni)"
    assert got.budget_amount == "max 1500 EUR a persona"
    assert got.travel_mode == "van"
    assert got.stay_preference == "agriturismo"


async def test_get_missing_raises():
    store = make_store()
    with pytest.raises(TripNotFoundError):
        await store.get("nope")


async def test_claim_acquired_once():
    store = make_store()
    trip = await store.create(make_trip())

    assert await store.claim(trip.id, ttl_seconds=300) is True
    assert await store.claim(trip.id, ttl_seconds=300) is False


async def test_claim_expires_after_ttl():
    store = make_store()
    trip = await store.create(make_trip())

    assert await store.claim(trip.id, ttl_seconds=1) is True
    import asyncio
    await asyncio.sleep(1.1)
    assert await store.claim(trip.id, ttl_seconds=1) is True


async def test_release_frees_lock():
    store = make_store()
    trip = await store.create(make_trip())

    assert await store.claim(trip.id, ttl_seconds=300) is True
    await store.release(trip.id)
    assert await store.claim(trip.id, ttl_seconds=300) is True


async def test_renew_extends_lock_ttl():
    store = make_store()
    trip = await store.create(make_trip())
    assert await store.claim(trip.id, ttl_seconds=2) is True

    await store.renew(trip.id, ttl_seconds=300)
    assert await store.claim(trip.id, ttl_seconds=2) is False


async def test_update_status_with_result():
    store = make_store()
    trip = await store.create(make_trip())

    await store.update_status(trip.id, TripStatus.DONE, result="ok")
    got = await store.get(trip.id)
    assert got.status == TripStatus.DONE
    assert got.result == "ok"


async def test_update_status_without_result():
    store = make_store()
    trip = await store.create(make_trip())

    await store.update_status(trip.id, TripStatus.ERROR)
    got = await store.get(trip.id)
    assert got.status == TripStatus.ERROR
    assert got.result is None
