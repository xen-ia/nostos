"""Router: TripResponse -> Jev state + atomic questions."""
from src.core.schemas import TripResponse
from src.services.apis.decisions import apply_threshold

ROUTER_QUESTIONS = {
    "travel_mode": {"type": "choice", "instructions": "Modalità di viaggio prevalente.",
                    "criteria": {"fixed": "base fissa", "road_trip": "tappe in auto o moto",
                                 "van_life": "dormire nel veicolo lungo il percorso",
                                 "sailing": "barca a vela o catamarano", "mixed": "combinazione"}},
    "needs_flights": {"type": "noul", "instructions": "Serve un volo per ARRIVARE? Se partenza e destinazione sono in paesi diversi, o la destinazione è un'isola, rispondere sì anche se in loco si guida."},
    "pace": {"type": "choice", "instructions": "Ritmo del viaggio, giudicato dalle giornate descritte: tappe tirate, tante cose al giorno o programma fitto e intenso; mix di giorni pieni e vuoti e moderato; lentezza, relax e giornate vuote e rilassato.",
             "criteria": {"rilassato": "lento e rilassato", "moderato": "moderato", "intenso": "intenso"}},
    "avoids_crowds": {"type": "noul", "instructions": "Cerca ESPLICITAMENTE posti autentici fuori dalle rotte turistiche (segnali come: autentico, non turistico, lontano dalle folle, fuori rotta)? Relax, natura o lentezza da soli NON bastano."},
    "stay_fit": {"type": "choice", "instructions": "Stile di pernottamento più adatto.",
                 "criteria": {"van": "van o camper", "camping": "campeggio", "homestay": "homestay o B&B",
                              "hotel": "hotel", "boat": "barca"}},
    "budget_sensitive": {"type": "noul", "instructions": "Budget esplicitamente RISTRETTO (segnali come: limitato, max, economico, low-cost)? Un importo dichiarato senza segnali di ristrettezza NON basta."},
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


def _parse_answer(item) -> tuple:
    """Live Jev shapes: choice -> {choice, confidence, probabilities},
    noul -> {noul: p}. Legacy {value, probability} fakes still accepted."""
    if not isinstance(item, dict):
        return item, 0.0
    if "value" in item:
        try:
            prob = float(item.get("probability", 0.0))
        except (TypeError, ValueError):
            prob = 0.0
        return item.get("value"), prob
    if item.get("type") == "choice":
        try:
            prob = float(item.get("confidence", ""))
        except (TypeError, ValueError):
            try:
                prob = max(float(v) for v in (item.get("probabilities", {}) or {}).values())
            except (TypeError, ValueError):
                prob = 0.0
        return item.get("choice"), prob
    if item.get("type") == "noul":
        try:
            p = float(item.get("noul", 0.0))
        except (TypeError, ValueError):
            p = 0.0
        return (p >= 0.5), max(p, 1.0 - p)
    return None, 0.0


async def route_trip(trip: TripResponse, client) -> dict:
    state = build_router_state(trip)
    raw = await client.decide(state, ROUTER_QUESTIONS)
    answers = raw.get("answers", {})
    decisions, bands, probs = {}, {}, {}
    for key in ROUTER_QUESTIONS:
        value, prob = _parse_answer(answers.get(key, {}))
        decisions[key] = value
        bands[key] = apply_threshold(prob)
        probs[key] = prob
    return {"decisions": decisions, "bands": bands, "probs": probs, "model": raw.get("model", "")}
