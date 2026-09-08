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


def test_geo_prompt_asks_secondary_airports():
    from src.core.prompts import build_geo_prompt
    prompt = build_geo_prompt(make_trip(), TripIntent(destination="Scozia"))
    assert "secondary" in prompt
