from src.core.models import TripIntent
from src.core.prompts import build_geo_prompt, build_target_prompt
from tests.fakes import make_trip


def test_target_prompt_carries_single_qualifier_guidance():
    intent = TripIntent(destination="Scozia", travel_mode="van_life",
                        mobility_preferences=["auto", "van"])
    prompt = build_target_prompt(make_trip(), intent, "- Skye (island)")
    assert "MODE GUIDANCE" in prompt
    assert "campervan parking" in prompt
    assert "accessibile auto parcheggio" not in prompt


def test_no_mechanical_enrichment_function():
    import src.core.orchestrator as orch
    assert not hasattr(orch.TripOrchestrator, "_enrich_queries_for_mode")


def test_rejected_moments_log_reasons(caplog):
    import asyncio
    import logging
    from src.core.models import LetterContent, TripIntent
    from src.core.orchestrator import TripOrchestrator
    from src.core.schemas import TripStatus, TripResponse
    from tests.fakes import FakeLLM

    letter = LetterContent(
        subject="X", opening="Si parte.",
        moments=[
            {"prose": "Corto.", "place_links": []},
            {"prose": "La piazzetta principale profuma di gelsomino mentre le persiane sbattono piano nel vento caldo del pomeriggio estivo.",
             "place_links": ["https://example.com/poi"]},
        ],
        closing="Ciao.")
    orch = TripOrchestrator.__new__(TripOrchestrator)
    orch._llm = FakeLLM(response=TripIntent(), letter_responses=[letter])
    orch._trip_id = "t"
    trip = TripResponse(id="t", status=TripStatus.PENDING, received_at="2026-09-20T00:00:00+00:00",
                        email="a@b.it", destination="X", free_text="x")
    curated = {"flights": [], "maps": [{"name": "POI", "link": "https://example.com/poi"}],
               "places": [], "rationale": ""}
    research = {"corpus": dict(curated), "curated": curated, "tool_calls": [], "geo": {}}
    with caplog.at_level(logging.INFO, logger="nostos.orchestrator"):
        try:
            asyncio.run(orch._compose_letter(trip, TripIntent(), research))
        except Exception:
            pass
    assert any("letter moment rejected (generic" in r.getMessage() for r in caplog.records)


def test_geo_prompt_asks_secondary_airports():
    from src.core.prompts import build_geo_prompt
    prompt = build_geo_prompt(make_trip(), TripIntent(destination="Scozia"))
    assert "secondary" in prompt
