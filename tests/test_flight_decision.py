from src.core.models import TripIntent
from src.core.prompts import build_intent_prompt
from tests.fakes import FakeDatabase, FakeLLM, make_trip
from tests.test_flight_matrix import EMAIL, _patch_searches, _run


def test_needs_flights_defaults_true_with_empty_rationale():
    intent = TripIntent(destination="Scozia")
    assert intent.needs_flights is True
    assert intent.flight_rationale == ""


def test_intent_prompt_guides_arrival_vs_local_decision():
    prompt = build_intent_prompt(make_trip())
    assert "needs_flights" in prompt
    assert "come arrivo" in prompt


def _llm_with_intent(intent):
    return FakeLLM(response=intent, email_response=EMAIL)


async def test_van_life_with_needs_flights_true_probes(monkeypatch):
    trip = make_trip(start_date="2026-09-01", end_date="2026-09-10")
    intent = TripIntent(
        destination="Scozia",
        departure_airport_code="MXP",
        destination_airport_code="EDI",
        travel_mode="van_life",
        needs_flights=True,
        flight_rationale="Volo per arrivare, van noleggiato in loco",
    )
    calls = []

    async def fake_flights(*args, **kwargs):
        calls.append(args)
        return []

    _patch_searches(monkeypatch, flights_fn=fake_flights)
    db = FakeDatabase()
    await _run(trip, _llm_with_intent(intent), db)
    assert calls != [], "needs_flights=true must probe even for van_life"
    assert db.saved[0]["package"]["geo"]["flight_rationale"] == "Volo per arrivare, van noleggiato in loco"


async def test_needs_flights_false_skips_with_reason(monkeypatch):
    trip = make_trip(start_date="2026-09-01", end_date="2026-09-10")
    # Airports present so the skip is caused by the LLM decision, not by missing codes.
    intent = TripIntent(destination="Lombardia", travel_mode="road_trip", needs_flights=False,
                        departure_airport_code="MXP", destination_airport_code="FCO",
                        flight_rationale="Gita in zona, si va in auto da casa")
    calls = []

    async def fake_flights(*args, **kwargs):
        calls.append(args)
        return []

    _patch_searches(monkeypatch, flights_fn=fake_flights)
    db = FakeDatabase()
    await _run(trip, _llm_with_intent(intent), db)
    assert calls == []
    skips = [tc for tc in db.saved[0]["package"]["tool_calls"] if tc.get("engine") == "google_flights"]
    assert skips == [{"engine": "google_flights", "skipped": True, "reason": "no_flights_needed"}]
