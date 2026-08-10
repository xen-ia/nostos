from pathlib import Path

from src.models import TripIntent
from src.trip_store import TripResponse

_PROMPTS_PATH = Path(__file__).parent / "system_prompt.md"

SYSTEM_PROMPT = _PROMPTS_PATH.read_text(encoding="utf-8")


def build_intent_prompt(trip: TripResponse) -> str:
    return f"""Extract the trip information from this request.

    Destination from the form: {trip.destination or "not specified"}
    Departure location from the form: {trip.departure_location or "not specified"}
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
) -> str:
    return f"""Write the trip email for this traveler.

    TRIP CONTEXT:
    Interests: {', '.join(intent.interests) or 'not specified'}
    Style sought: {', '.join(intent.style) or 'not specified'}
    Pace: {intent.pace or 'not specified'}

    RESOURCES AVAILABLE (use these):
    Flights:
    {flights_block}

    Points of interest:
    {maps_block}

    Accommodation:
    {places_block}
    """