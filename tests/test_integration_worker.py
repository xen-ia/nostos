"""Integration test: real Redis + Postgres + ARQ worker, faked LLM/email/SerpAPI.

Skips automatically when the services are not reachable (no docker compose up).
Set NOSTOS_REDIS_URL / NOSTOS_POSTGRES_URL to point at the test services.
"""
import asyncio
import os

import pytest

os.environ.setdefault("NOSTOS_REDIS_URL", "redis://localhost:6380/0")
os.environ.setdefault("NOSTOS_POSTGRES_URL", "postgresql://postgres:postgres@localhost:5433/nostos")

from arq import Worker  # noqa: E402
from arq.connections import RedisSettings  # noqa: E402

import src.infrastructure.worker as worker_module  # noqa: E402
from src.core.schemas import TripStatus  # noqa: E402
from src.services.trip_store import TripStore  # noqa: E402
from tests.fakes import FakeEmailSender, FakeLLM, make_trip  # noqa: E402
from tests.test_orchestrator import EMAIL, INTENT  # noqa: E402


def _services_up() -> bool:
    try:
        import asyncpg

        async def _probe():
            pool = await asyncpg.create_pool(os.environ["NOSTOS_POSTGRES_URL"])
            await pool.fetchval("SELECT 1")
            await pool.close()

        asyncio.run(_probe())
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _services_up(), reason="Redis/Postgres not reachable")


@pytest.fixture
def test_env():
    from src.settings import get_settings

    os.environ["NOSTOS_REDIS_URL"] = "redis://localhost:6380/0"
    os.environ["NOSTOS_POSTGRES_URL"] = "postgresql://postgres:postgres@localhost:5433/nostos"
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _make_pool():
    import asyncpg

    return await asyncpg.create_pool(os.environ["NOSTOS_POSTGRES_URL"])


async def _reset_db(pool):
    await pool.execute("DELETE FROM trip_history")


async def test_end_to_end_worker_done(monkeypatch, test_env):
    import redis.asyncio as redis_async
    from src.infrastructure.jobs import run_trip_job

    redis = redis_async.from_url(os.environ["NOSTOS_REDIS_URL"], decode_responses=True)
    pool = await _make_pool()
    await _reset_db(pool)

    store = TripStore(redis=redis, ttl_seconds=86400)
    trip = await store.create(make_trip())

    from arq import create_pool

    arq = await create_pool(RedisSettings.from_dsn(os.environ["NOSTOS_REDIS_URL"]))
    await arq.enqueue_job("run_trip_job", trip.id, _queue_name=worker_module.QUEUE_NAME)

    llm = FakeLLM(response=INTENT, email_response=EMAIL)
    email = FakeEmailSender()

    def fake_build_llm(settings):
        return llm

    def fake_email(**kwargs):
        return email

    async def fake_flights(*args, **kwargs):
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01", "price_eur": 320, "link": "https://example.com/flight"}]

    async def fake_maps(*args, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(*args, **kwargs):
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.infrastructure.jobs.build_llm_client", fake_build_llm)
    monkeypatch.setattr("src.infrastructure.jobs.EmailSender", fake_email)
    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    worker = Worker(
        functions=[run_trip_job],
        redis_settings=RedisSettings.from_dsn(os.environ["NOSTOS_REDIS_URL"]),
        burst=True,
        max_jobs=1,
        queue_name=worker_module.QUEUE_NAME,
        ctx={"pg_pool": pool},
    )
    await worker.main()

    got = await store.get(trip.id)
    assert got.status == TripStatus.DONE
    assert len(email.sent) == 1

    rows = await pool.fetch("SELECT status FROM trip_history WHERE id = $1", trip.id)
    assert rows[0]["status"] == TripStatus.DONE.value

    assert await store.claim(trip.id, ttl_seconds=300) is True

    await arq.aclose()
    await redis.aclose()
    await pool.close()
