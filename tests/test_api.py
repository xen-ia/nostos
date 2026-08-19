import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.errors import register_exception_handlers
from src.api.middleware import RequestIDMiddleware
from src.api.routers import trips as trips_router
from src.core.schemas import TripStatus
from tests.fakes import FakeDatabase, FakeLLM, make_store
from tests.test_orchestrator import EMAIL, INTENT


class FakeArq:
    def __init__(self):
        self.enqueued: list[tuple[str, list]] = []

    async def enqueue_job(self, function, *args, **kwargs):
        self.enqueued.append((function, list(args), kwargs))


def make_app(store=None, arq=None, api_token: str = "", rate_limit_max: int = 10, window: int = 60, db=None, whitelist_daily_max: int = 5):
    store = store or make_store()
    arq = arq or FakeArq()
    llm = FakeLLM(response=INTENT, email_response=EMAIL)

    app = FastAPI()
    app.state.redis = store._redis
    app.state.arq = arq
    app.state.pg_pool = None
    app.state.trips_created = 0

    from src.settings import Settings

    app.state.settings = Settings(
        api_token=api_token,
        rate_limit_max=rate_limit_max,
        rate_limit_window_seconds=window,
        whitelist_daily_max=whitelist_daily_max,
    )

    app.include_router(trips_router.router)
    app.add_middleware(RequestIDMiddleware)
    from main import add_health_routes

    add_health_routes(app)
    register_exception_handlers(app)

    app.dependency_overrides[trips_router.get_trip_store] = lambda: store
    app.dependency_overrides[trips_router.get_arq] = lambda: arq
    app.dependency_overrides[trips_router.get_database] = lambda: (db or FakeDatabase())

    return app, store, arq


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_create_trip_valid_enqueues_job():
    app, store, arq = make_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/trips",
            json={
                "email": "test@example.com",
                "destination": "Tokyo",
                "start_date": "2026-09-01",
                "end_date": "2026-09-10",
                "travelers_count": 2,
                "travelers_type": "coppia",
            },
        )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == TripStatus.PENDING.value
    assert "id" in data
    assert resp.headers.get("Location") == f"/api/v1/trips/{data['id']}"
    assert resp.headers.get("X-Request-ID")
    assert len(arq.enqueued) == 1
    fn, args, kwargs = arq.enqueued[0]
    assert fn == "run_trip_job"
    assert args == [data["id"]]


def test_create_trip_invalid_travelers():
    app, *_ = make_app()
    with TestClient(app) as client:
        resp = client.post("/api/v1/trips", json={"email": "test@example.com", "travelers_count": 0})
    assert resp.status_code == 422
    body = resp.json()
    assert body["type"] == "https://xen-ia.org/problems/validation_error"
    assert body["request_id"]


def test_create_trip_invalid_email():
    app, *_ = make_app()
    with TestClient(app) as client:
        resp = client.post("/api/v1/trips", json={"email": "nope"})
    assert resp.status_code == 422


def test_create_trip_invalid_travelers_type():
    app, *_ = make_app()
    with TestClient(app) as client:
        resp = client.post("/api/v1/trips", json={"email": "a@b.com", "travelers_type": "gruppone"})
    assert resp.status_code == 422


def test_get_missing_trip_404_problem_json():
    app, *_ = make_app()
    with TestClient(app) as client:
        resp = client.get("/api/v1/trips/nope")
    assert resp.status_code == 404
    body = resp.json()
    assert body["type"].endswith("/trip_not_found")
    assert body["request_id"]


def test_idempotency_key_reuses_trip():
    app, store, arq = make_app()
    payload = {"email": "test@example.com", "destination": "Kyoto"}
    with TestClient(app) as client:
        first = client.post("/api/v1/trips", json=payload, headers={"Idempotency-Key": "abc123"})
        second = client.post("/api/v1/trips", json=payload, headers={"Idempotency-Key": "abc123"})
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert len(arq.enqueued) == 1


def test_auth_required_when_token_configured():
    app, *_ = make_app(api_token="sekret")
    with TestClient(app) as client:
        resp = client.post("/api/v1/trips", json={"email": "a@b.com"})
        assert resp.status_code == 401
        assert resp.json()["type"].endswith("/unauthorized")
        ok = client.post(
            "/api/v1/trips",
            json={"email": "a@b.com"},
            headers=auth_headers("sekret"),
        )
        assert ok.status_code == 202


def test_whitelist_denies_unlisted_email():
    db = FakeDatabase(whitelist={"test@example.com"})
    app, *_ = make_app(db=db)
    with TestClient(app) as client:
        resp = client.post("/api/v1/trips", json={"email": "other@example.com", "destination": "Tokyo"})
    assert resp.status_code == 403
    body = resp.json()
    assert body["type"].endswith("/not_whitelisted")
    assert body["request_id"]


def test_whitelist_allows_listed_email():
    db = FakeDatabase(whitelist={"test@example.com"})
    app, *_ = make_app(db=db)
    with TestClient(app) as client:
        resp = client.post("/api/v1/trips", json={"email": "test@example.com", "destination": "Tokyo"})
    assert resp.status_code == 202


def test_whitelist_empty_denies_all():
    db = FakeDatabase(whitelist=set())
    app, *_ = make_app(db=db)
    with TestClient(app) as client:
        resp = client.post("/api/v1/trips", json={"email": "test@example.com"})
    assert resp.status_code == 403
    assert resp.json()["type"].endswith("/not_whitelisted")


def test_whitelist_daily_limit_per_email():
    db = FakeDatabase(whitelist={"test@example.com"})
    app, *_ = make_app(db=db, whitelist_daily_max=2)
    with TestClient(app) as client:
        r1 = client.post("/api/v1/trips", json={"email": "test@example.com", "destination": "Tokyo"})
        r2 = client.post("/api/v1/trips", json={"email": "test@example.com", "destination": "Osaka"})
        r3 = client.post("/api/v1/trips", json={"email": "test@example.com", "destination": "Kyoto"})
    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r3.status_code == 429
    assert r3.json()["type"].endswith("/rate_limited")


def test_whitelist_daily_limit_separate_per_email():
    db = FakeDatabase(whitelist={"a@example.com", "b@example.com"})
    app, *_ = make_app(db=db, whitelist_daily_max=1)
    with TestClient(app) as client:
        a1 = client.post("/api/v1/trips", json={"email": "a@example.com", "destination": "Tokyo"})
        b1 = client.post("/api/v1/trips", json={"email": "b@example.com", "destination": "Osaka"})
    assert a1.status_code == 202
    assert b1.status_code == 202


def test_rate_limit_exceeded():
    app, *_ = make_app(rate_limit_max=2, window=60)
    with TestClient(app) as client:
        r1 = client.post("/api/v1/trips", json={"email": "a@b.com"})
        r2 = client.post("/api/v1/trips", json={"email": "a@b.com"})
        r3 = client.post("/api/v1/trips", json={"email": "a@b.com"})
    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r3.status_code == 429
    assert r3.json()["type"].endswith("/rate_limited")
    assert r3.headers.get("Retry-After")


def test_honeypot_always_forbidden():
    app, *_ = make_app()
    with TestClient(app) as client:
        resp = client.post("/api/v1/trips/admin/reset")
    assert resp.status_code == 403
    assert resp.json()["type"].endswith("/forbidden")


def test_healthz_and_metrics():
    app, store, arq = make_app()
    with TestClient(app) as client:
        client.post("/api/v1/trips", json={"email": "a@b.com", "destination": "Roma"})
        health = client.get("/healthz")
        metrics = client.get("/metrics")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert metrics.status_code == 200
    body = metrics.text
    assert "nostos_uptime_seconds " in body
    assert "nostos_trips_created_total 1" in body


def test_readyz_degraded_without_services():
    app, *_ = make_app()
    with TestClient(app) as client:
        resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"
    assert "redis" in resp.json()["checks"]


def test_feedback_endpoint():
    app, store, arq = make_app()
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/trips",
            json={"email": "test@example.com", "destination": "Roma"},
        )
        trip_id = created.json()["id"]
        resp = client.post(
            f"/api/v1/trips/{trip_id}/feedback",
            json={"rating": 5, "comment": "Bellissimo"},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["trip_id"] == trip_id
    assert body["rating"] == 5
    assert body["comment"] == "Bellissimo"
