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
    assert ROUTER_QUESTIONS["needs_flights"]["type"] == "bool"
