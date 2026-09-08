import io
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.errors import register_exception_handlers
from src.api.middleware import RequestIDMiddleware
from src.api.routers import stt as stt_router
from src.settings import get_settings, Settings
from tests.fakes import make_redis


def make_stt_app(settings_overrides: dict | None = None):
    """Create FastAPI app with stt router and FakeRedis."""
    redis = make_redis()
    app = FastAPI()
    app.state.redis = redis
    # ensure settings reflect API token disabled etc
    settings_kwargs = dict(
        openai_api_key="sk-test",
        stt_model="gpt-transcribe",
        stt_max_mb=25,
        api_token="",
        rate_limit_max=10,
        rate_limit_window_seconds=60,
    )
    if settings_overrides:
        settings_kwargs.update(settings_overrides)
    settings = Settings(**settings_kwargs)
    app.state.settings = settings
    app.include_router(stt_router.router)
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    # override get_settings to return our custom settings
    app.dependency_overrides[get_settings] = lambda: settings
    return app, settings, redis


def test_stt_requires_openai_key():
    app, settings, _ = make_stt_app(settings_overrides={"openai_api_key": ""})
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/stt",
            files={"audio": ("audio.webm", io.BytesIO(b"fake audio data"), "audio/webm")},
        )
    assert resp.status_code == 503
    body = resp.json()
    assert "stt" in body["detail"].lower() or "configured" in body["detail"].lower()


def test_stt_invalid_content_type():
    app, _, _ = make_stt_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/stt",
            files={"audio": ("file.txt", io.BytesIO(b"hello"), "text/plain")},
        )
    assert resp.status_code == 400
    body = resp.json()
    assert body["type"].endswith("/bad_request")


def test_stt_too_large():
    # set max to 1 MB, send 2 MB
    app, _, _ = make_stt_app(settings_overrides={"stt_max_mb": 1})
    big_data = b"a" * (2 * 1024 * 1024)
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/stt",
            files={"audio": ("audio.webm", io.BytesIO(big_data), "audio/webm")},
        )
    assert resp.status_code == 413


def test_stt_too_large_via_size_attribute():
    """If UploadFile.size is set, early check should also return 413 without reading full data."""
    app, _, _ = make_stt_app(settings_overrides={"stt_max_mb": 1})
    big_data = b"a" * (2 * 1024 * 1024)
    # We still send 2MB; handler checks audio.size and len(data) both trigger 413
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/stt",
            files={"audio": ("audio.webm", io.BytesIO(big_data), "audio/webm")},
        )
    assert resp.status_code == 413


def test_stt_transcribes_audio():
    app, _, _ = make_stt_app()
    mock_text = "ciao mare"
    with patch("src.api.routers.stt.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_instance.audio.transcriptions.create.return_value = type("obj", (), {"text": mock_text})()
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/stt",
                files={"audio": ("audio.webm", io.BytesIO(b"fake audio bytes"), "audio/webm")},
            )
        assert resp.status_code == 200
        assert resp.json() == {"text": mock_text}
        # verify OpenAI called with correct model and language
        MockOpenAI.assert_called_once_with(api_key="sk-test")
        call_kwargs = mock_instance.audio.transcriptions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-transcribe"
        assert call_kwargs["language"] == "it"
        # file should be BytesIO with name
        assert hasattr(call_kwargs["file"], "read")
        assert getattr(call_kwargs["file"], "name", "") == "audio.webm"


def test_stt_transcription_failure_returns_502():
    app, _, _ = make_stt_app()
    with patch("src.api.routers.stt.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_instance.audio.transcriptions.create.side_effect = Exception("openai down")
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/stt",
                files={"audio": ("audio.webm", io.BytesIO(b"fake audio bytes"), "audio/webm")},
            )
        assert resp.status_code == 502


def test_stt_rate_limited():
    app, _, _ = make_stt_app()
    mock_text = "ciao"
    with patch("src.api.routers.stt.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_instance.audio.transcriptions.create.return_value = type("obj", (), {"text": mock_text})()
        with TestClient(app) as client:
            # 10 allowed, 11th should be 429
            for _ in range(10):
                r = client.post(
                    "/api/v1/stt",
                    files={"audio": ("audio.webm", io.BytesIO(b"fake"), "audio/webm")},
                )
                assert r.status_code == 200
            r = client.post(
                "/api/v1/stt",
                files={"audio": ("audio.webm", io.BytesIO(b"fake"), "audio/webm")},
            )
            assert r.status_code == 429


def test_stt_allows_audio_prefix_fallback():
    """Any audio/* should be accepted even if not in explicit ALLOWED_CT."""
    app, _, _ = make_stt_app()
    with patch("src.api.routers.stt.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_instance.audio.transcriptions.create.return_value = type("obj", (), {"text": "ok"})()
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/stt",
                files={"audio": ("audio.webm", io.BytesIO(b"fake"), "audio/x-custom")},
            )
        assert resp.status_code == 200


def test_stt_rejects_empty_file():
    app, _, _ = make_stt_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/stt",
            files={"audio": ("audio.webm", io.BytesIO(b""), "audio/webm")},
        )
    assert resp.status_code == 400
