import asyncio
from src.core.models import TripPlan, DayStop

class _FakeLLM:
    async def extract(self, prompt, model):
        assert "Giorni" in prompt or "fasi" in prompt
        return TripPlan(days=[DayStop(day_label="Giorni 1-7 · X", poi_refs=[0], transition="tappe corte.")])

def test_plan_itinerary_no_dates_returns_empty():
    from src.core.schemas import TripResponse, TripStatus
    from src.core.orchestrator import TripOrchestrator
    orch = TripOrchestrator.__new__(TripOrchestrator)
    trip = TripResponse(id="t", status=TripStatus.PENDING, received_at="2026-09-20T00:00:00+00:00",
        email="a@b.it", destination="Creta", free_text="van")
    plan = asyncio.run(orch._plan_itinerary(trip, __import__("src.core.models", fromlist=["TripIntent"]).TripIntent(), {"flights": [], "maps": [], "places": []}))
    assert plan.days == []


def test_plan_itinerary_llm_error_falls_back_to_single_phase():
    import asyncio
    from src.core.models import TripIntent
    from src.core.orchestrator import TripOrchestrator
    from src.core.schemas import TripResponse, TripStatus

    class _BoomLLM:
        async def extract(self, prompt, model, max_tokens=1024):
            raise RuntimeError("truncated")

    orch = TripOrchestrator.__new__(TripOrchestrator)
    orch._llm = _BoomLLM()
    trip = TripResponse(id="t", status=TripStatus.PENDING, received_at="2026-09-20T00:00:00+00:00",
        email="a@b.it", destination="Creta", start_date="2027-07-30", end_date="2027-08-30",
        free_text="van")
    curated = {"flights": [], "maps": [{"name": "X"}], "places": [{"name": "Y"}]}
    plan = asyncio.run(orch._plan_itinerary(trip, TripIntent(), curated))
    assert len(plan.days) == 1
    assert plan.days[0].day_label == "Le tappe"
    assert plan.days[0].poi_refs == [0]
    assert plan.days[0].stay_refs == [0]
