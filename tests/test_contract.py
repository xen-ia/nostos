"""Contract test: the mock frontend in docs/index.html must match the API.

The frontend posts a JSON payload built from the form; the API must accept
exactly those fields, and the fetch URL must point at the versioned route.
"""
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.errors import register_exception_handlers
from src.api.middleware import RequestIDMiddleware
from src.api.routers import trips as trips_router
from tests.fakes import FakeDatabase, make_store
from tests.test_api import FakeArq, make_app

FRONTEND = "docs/index.html"


def _frontend_source():
    with open(FRONTEND, encoding="utf-8") as fh:
        return fh.read()


def test_frontend_points_at_versioned_api_base():
    src = _frontend_source()
    assert re.search(r'const API_BASE = "https://nostos.xen-ia.org/api/v1";', src)
    assert 'fetch(`${API_BASE}/trips`' in src


def test_frontend_posts_exactly_schema_fields():
    """Every key the frontend sends must be a TripCreateRequest field, and the
    request must carry all of them (no field drift between UI and API)."""
    from src.core.schemas import TripCreateRequest

    src = _frontend_source()
    block = re.search(r"const payload = \{(.*?)\};", src, re.DOTALL)
    assert block, "payload object not found in frontend"
    payload_keys = set(re.findall(r"^\s{6}(\w+):", block.group(1), re.MULTILINE))

    schema_fields = set(TripCreateRequest.model_fields.keys())
    assert payload_keys == schema_fields, (
        f"Frontend payload fields {payload_keys} != API schema fields {schema_fields}"
    )


def test_frontend_payload_round_trips_through_api():
    """Build the exact payload shape the frontend produces and POST it."""
    app, *_ = make_app()
    payload = {
        "email": "nome@esempio.com",
        "destination": "Puglia",
        "start_date": "2026-08-20",
        "end_date": "2026-08-27",
        "travelers_count": 2,
        "travelers_type": "coppia",
        "budget_range": "medio",
        "departure_location": "Bari",
        "free_text": "vogliamo il mare e buon cibo",
        "travelers_composition": "2 adulti",
        "budget_amount": "max 1500 EUR",
        "travel_mode": "van",
        "stay_preference": "agriturismo",
    }
    with TestClient(app) as client:
        resp = client.post("/api/v1/trips", json=payload)
    assert resp.status_code == 202
    assert resp.headers["Location"].startswith("/api/v1/trips/")
    data = resp.json()
    assert data["destination"] == "Puglia"
    assert data["travelers_count"] == 2


def test_flexible_dates_field_rejected():
    """flexible_dates was removed from the contract (ADR-007): the API must
    reject it instead of silently ignoring it."""
    app, *_ = make_app()
    payload = {
        "email": "nome@esempio.com",
        "destination": "Puglia",
        "start_date": "2026-08-20",
        "end_date": "2026-08-27",
        "travelers_count": 2,
        "travelers_type": "coppia",
        "budget_range": "medio",
        "departure_location": "Bari",
        "free_text": "vogliamo il mare e buon cibo",
        "travelers_composition": "2 adulti",
        "budget_amount": "max 1500 EUR",
        "travel_mode": "van",
        "stay_preference": "agriturismo",
        "flexible_dates": True,
    }
    with TestClient(app) as client:
        resp = client.post("/api/v1/trips", json=payload)
    assert resp.status_code == 422
