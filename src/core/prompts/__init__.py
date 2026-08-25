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
    - Copy preferences ONLY from the fields and free text above; leave everything else null.
    """


def build_period_prompt(trip: TripResponse, intent: TripIntent, today_iso: str) -> str:
    return f"""The traveler gave no dates. Propose the best travel windows for this trip.

    Today is {today_iso}.
    Destination: {trip.destination or "not specified"}
    Interests: {', '.join(intent.interests) or 'not specified'}
    Style: {', '.join(intent.style) or 'not specified'}

    Consider the best season for the destination (climate, crowding, prices) and the traveler's interests.
    Return at most 2 windows in the future, each with a short Italian rationale.
    """


def build_target_prompt(trip: TripResponse, intent: TripIntent, anchors_block: str) -> str:
    return f"""You plan targeted research for this trip. You are given exploration anchors
    (areas, landmark types) discovered for the destination.

    TRIP CONTEXT (verbatim user brief below — do NOT assume preferences not present here):
    Destination: {trip.destination or "not specified"}
    Interests: {', '.join(intent.interests) or 'not specified'}
    Style: {', '.join(intent.style) or 'not specified'}
    Pace: {intent.pace or 'not specified'}

    EXPLORATION ANCHORS:
    {anchors_block}

    USER FREE TEXT (verbatim):
    "{trip.free_text}"

    Propose at most 4 targeted Google-Maps search queries (same language as the destination)
    that dig INTO the anchors along the brief's interests and style — e.g. specific
    neighborhoods, niche venues, quiet alternatives. Each query must derive from an anchor.
    """


def build_curation_prompt(trip: TripResponse, intent: TripIntent, corpus_blocks: str) -> str:
    return f"""Select the best resources for this traveler from the numbered corpus below.

    TRIP CONTEXT:
    Interests: {', '.join(intent.interests) or 'not specified'}
    Style: {', '.join(intent.style) or 'not specified'}
    Pace: {intent.pace or 'not specified'}

    CORPUS (numbered with zero-based indices in brackets; reference ONLY these indices):
    {corpus_blocks}

    Rules: pick by merit for THIS brief — quality and fit, never filler. Zero items in a
    category is a valid choice when nothing fits. Return zero-based indices only, plus a
    short Italian rationale.
    """


def build_email_prompt(
    intent: TripIntent,
    flights_block: str,
    maps_block: str,
    places_block: str,
    trip: TripResponse | None = None,
) -> str:
    return f"""Write the trip email for this traveler.

    TRIP CONTEXT (only these preferences exist — never invent others):
    Interests: {', '.join(intent.interests) or 'not specified'}
    Style sought: {', '.join(intent.style) or 'not specified'}
    Pace: {intent.pace or 'not specified'}
    Travelers: {trip.travelers_composition if trip else 'not specified'}
    Budget: {trip.budget_amount if trip else 'not specified'}
    Travel mode: {trip.travel_mode if trip else 'not specified'}
    Stay preference: {trip.stay_preference if trip else 'not specified'}

    USER FREE TEXT (verbatim):
    "{trip.free_text if trip else ''}"

    RESOURCES AVAILABLE (IDs in brackets; cite ONLY these):
    Flights:
    {flights_block}

    Points of interest:
    {maps_block}

    Accommodation:
    {places_block}
    """