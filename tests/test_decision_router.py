from src.core.decision_router import build_router_state, ROUTER_QUESTIONS
from src.core.schemas import TripResponse, TripStatus


def _trip():
    return TripResponse(id="t1", status=TripStatus.PENDING, received_at="2026-09-20T00:00:00+00:00",
        email="a@b.it", destination="Creta", departure_location="Italy",
        start_date="2027-07-30", end_date="2027-08-30", flexible_dates=False,
        travelers_count=2, travelers_type="coppia", free_text="cibo e tradizioni locali, mare e relax, ritmo lento, lontano dalle folle, van")


def test_router_state_and_questions():
    state = build_router_state(_trip())
    assert state["destination"] == "Creta"
    assert "van" in state["free_text"]
    assert ROUTER_QUESTIONS["travel_mode"]["type"] == "choice"
    assert ROUTER_QUESTIONS["needs_flights"]["type"] == "noul"
    assert set(ROUTER_QUESTIONS["travel_mode"]["criteria"]) == {"fixed", "road_trip", "van_life", "sailing", "mixed"}


LIVE_CRETA = {"model": "jev-1.13.0", "answers": {
    "travel_mode": {"type": "choice", "choice": "road_trip", "confidence": 0.62,
                    "probabilities": {"road_trip": 0.7, "van_life": 0.18, "sailing": 0.0, "fixed": 0.01, "mixed": 0.11}},
    "needs_flights": {"type": "noul", "noul": 0.82},
    "pace": {"type": "choice", "choice": "rilassato", "confidence": 1.0,
             "probabilities": {"moderato": 0.0, "intenso": 0.0, "rilassato": 1.0}},
    "avoids_crowds": {"type": "noul", "noul": 0.95},
    "stay_fit": {"type": "choice", "choice": "van", "confidence": 0.89,
                 "probabilities": {"homestay": 0.01, "van": 0.91, "boat": 0.0, "hotel": 0.0, "camping": 0.08}},
    "budget_sensitive": {"type": "noul", "noul": 0.07},
}}


def test_route_trip_parses_live_jev_format():
    import asyncio
    from src.core.decision_router import route_trip

    class _FakeJev:
        async def decide(self, state, questions):
            assert questions["needs_flights"]["type"] == "noul"
            return LIVE_CRETA

    out = asyncio.run(route_trip(_trip(), _FakeJev()))
    assert out["decisions"]["travel_mode"] == "road_trip"
    assert out["decisions"]["needs_flights"] is True
    assert out["decisions"]["budget_sensitive"] is False
    assert out["bands"]["travel_mode"] == "review"
    assert out["bands"]["needs_flights"] == "review"
    assert out["bands"]["pace"] == "auto"
    assert out["bands"]["budget_sensitive"] == "auto"
    assert out["model"] == "jev-1.13.0"
