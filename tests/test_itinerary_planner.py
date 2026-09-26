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
