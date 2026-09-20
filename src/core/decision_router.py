"""Router: TripResponse -> Jev state + atomic questions."""
from src.core.schemas import TripResponse
from src.services.apis.decisions import apply_threshold

ROUTER_QUESTIONS = {
    "travel_mode": {"type": "choice", "choices": ["fixed", "road_trip", "van_life", "sailing", "mixed"], "instructions": "Modalità prevalente da free_text e campi form."},
    "needs_flights": {"type": "bool", "instructions": "True se serve volo per arrivare (paese diverso, isola, lunghe distanze)."},
    "pace": {"type": "choice", "choices": ["rilassato", "moderato", "intenso"], "instructions": "Ritmo del viaggio."},
    "avoids_crowds": {"type": "bool", "instructions": "True se cerca posti autentici lontano dalle folle."},
    "stay_fit": {"type": "choice", "choices": ["van", "camping", "homestay", "hotel", "boat"], "instructions": "Pernottamento più adatto."},
    "budget_sensitive": {"type": "bool", "instructions": "True se budget limitato o sensibilità prezzo esplicita."},
}


def build_router_state(trip: TripResponse) -> dict:
    return {
        "destination": trip.destination or "",
        "departure_location": trip.departure_location or "",
        "start_date": trip.start_date or "",
        "end_date": trip.end_date or "",
        "flexible_dates": bool(trip.flexible_dates),
        "travelers_count": trip.travelers_count,
        "travelers_type": trip.travelers_type or "",
        "travel_mode_hint": trip.travel_mode or "",
        "stay_hint": trip.stay_preference or "",
        "budget_amount": trip.budget_amount or "",
        "free_text": trip.free_text or "",
    }


async def route_trip(trip: TripResponse, client) -> dict:
    state = build_router_state(trip)
    raw = await client.decide(state, ROUTER_QUESTIONS)
    answers = raw.get("answers", {})
    decisions, bands, probs = {}, {}, {}
    for key in ROUTER_QUESTIONS:
        item = answers.get(key, {})
        value = item.get("value") if isinstance(item, dict) else item
        try:
            prob = float(item.get("probability", 0.0)) if isinstance(item, dict) else 0.0
        except (TypeError, ValueError):
            prob = 0.0
        decisions[key] = value
        bands[key] = apply_threshold(prob)
        probs[key] = prob
    return {"decisions": decisions, "bands": bands, "probs": probs, "model": raw.get("model", "")}
