"""OpenAI Decisions provider: System One <-> OpenAI /v1/decisions adapter."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from src.services.apis.decisions import (
    DecisionError,
    JevDecisionClient,
    OpenAIDecisionClient,
    build_decision_client,
    effective_decision_model,
)


def _client(handler, model=None):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    kwargs = {"model": model} if model else {}
    return OpenAIDecisionClient(api_key="k", client=http, **kwargs), http


async def test_openai_request_translates_system_one_questions():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": []})

    client, http = _client(handler)
    state = {"destination": "Creta", "free_text": "van mare relax"}
    questions = {
        "needs_flights": {"type": "noul", "instructions": "Serve un volo?"},
        "travel_mode": {"type": "choice", "instructions": "Modalità?",
                        "criteria": {"fixed": "base fissa", "van_life": "van"}},
    }
    try:
        await client.decide(state, questions)
    finally:
        await http.aclose()

    assert captured["url"] == "https://api.openai.com/v1/decisions"
    assert captured["auth"] == "Bearer k"
    body = captured["body"]
    assert body["model"] == "gpt-6-luna"
    assert "van mare relax" in body["input"]  # state serialised into input
    qs = {q["name"]: q for q in body["questions"]}
    assert qs["needs_flights"]["type"] == "predicate"
    assert qs["needs_flights"]["instructions"] == "Serve un volo?"
    assert "choices" not in qs["needs_flights"]
    assert qs["travel_mode"]["type"] == "choice"
    assert qs["travel_mode"]["choices"] == [
        {"value": "fixed", "description": "base fissa"},
        {"value": "van_life", "description": "van"},
    ]


async def test_openai_response_maps_back_to_system_one():
    def handler(request):
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            {"type": "predicate", "name": "needs_flights", "probability": 0.91},
            {"type": "choice", "name": "travel_mode", "choice": "van_life", "confidence": 0.88},
            {"type": "refusal", "name": "budget_sensitive"},
        ]})

    client, http = _client(handler)
    try:
        out = await client.decide({}, {"needs_flights": {"type": "noul"}})
    finally:
        await http.aclose()

    assert out["model"] == "gpt-6-luna"
    assert out["answers"]["needs_flights"] == {"type": "noul", "noul": 0.91}
    assert out["answers"]["travel_mode"] == {"type": "choice", "choice": "van_life", "confidence": 0.88}
    assert "budget_sensitive" not in out["answers"]  # refusal -> no answer -> fallback band


async def test_openai_http_error_raises_decision_error():
    def handler(request):
        return httpx.Response(429, json={"error": "rate limited"})

    client, http = _client(handler)
    try:
        with pytest.raises(DecisionError) as excinfo:
            await client.decide({}, {})
    finally:
        await http.aclose()

    assert "429" in str(excinfo.value)
    assert "rate limited" in str(excinfo.value)


def test_build_decision_client_selects_provider():
    base = dict(decision_model="", decision_timeout=5.0, openai_api_key="", typesafe_api_key="")

    assert build_decision_client(SimpleNamespace(decision_provider="llm-fallback", **base)) is None

    no_key = SimpleNamespace(decision_provider="openai", **base)
    assert build_decision_client(no_key) is None

    openai_on = SimpleNamespace(decision_provider="openai", **{**base, "openai_api_key": "sk-1"})
    client = build_decision_client(openai_on)
    assert isinstance(client, OpenAIDecisionClient)
    asyncio.run(client.close())

    jev_on = SimpleNamespace(decision_provider="jev", **{**base, "typesafe_api_key": "t-1"})
    client = build_decision_client(jev_on)
    assert isinstance(client, JevDecisionClient)
    asyncio.run(client.close())


def test_effective_decision_model_pins_per_provider():
    assert effective_decision_model("openai", "") == "gpt-6-luna"
    assert effective_decision_model("jev", "") == "jev-1.13.0"
    assert effective_decision_model("openai", "custom") == "custom"
