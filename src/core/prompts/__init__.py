from functools import lru_cache
from pathlib import Path

from src.core.models import TripIntent
from src.core.schemas import TripResponse

_PROMPTS_PATH = Path(__file__).parent / "system_prompt.md"


@lru_cache
def get_system_prompt() -> str:
    return _PROMPTS_PATH.read_text(encoding="utf-8")


def build_intent_prompt(trip: TripResponse) -> str:
    return f"""Extract the trip information from this request.

    Destination from the form: {trip.destination or "not specified"}
    Departure location from the form: {trip.departure_location or "not specified"}
    Travelers composition: {trip.travelers_composition or "not specified"}
    Budget amount: {trip.budget_amount or "not specified"}
    Travel mode: {trip.travel_mode or "not specified"}
    Stay preference: {trip.stay_preference or "not specified"}
    User's free text: "{trip.free_text}"

    IATA CODES: always infer the main international airport, even when not explicitly named:
    - for a city, use its main airport (e.g. Milan -> MXP);
    - for a country or region, use its main international airport (e.g. Cameroon -> NSI, Japan -> HND).
    Do not leave the fields empty when the destination is recognizable.
    """


def build_email_prompt(
    intent: TripIntent,
    flights_block: str,
    maps_block: str,
    places_block: str,
    trip: TripResponse | None = None,
) -> str:
    return f"""Write the trip email for this traveler.

    TRIP CONTEXT:
    Interests: {', '.join(intent.interests) or 'not specified'}
    Style sought: {', '.join(intent.style) or 'not specified'}
    Pace: {intent.pace or 'not specified'}
    Travelers composition: {trip.travelers_composition if trip else 'not specified'}
    Budget amount: {trip.budget_amount if trip else 'not specified'}
    Travel mode: {trip.travel_mode if trip else 'not specified'}
    Stay preference: {trip.stay_preference if trip else 'not specified'}

    RESOURCES AVAILABLE (use these):
    Flights:
    {flights_block}

    Points of interest:
    {maps_block}

    Accommodation:
    {places_block}
    """