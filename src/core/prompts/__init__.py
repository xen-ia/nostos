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
    Travelers count: {trip.travelers_count}
    Travelers type: {trip.travelers_type or "not specified"}
    Budget amount: {trip.budget_amount or "not specified"}
    Travel mode: {trip.travel_mode or "not specified"}
    Stay preference: {trip.stay_preference or "not specified"}
    User's free text: "{trip.free_text}"

    IATA CODES: always infer the main international airport, even when not explicitly named:
    - for a city, use its main airport (e.g. Milan -> MXP);
    - for a country or region, use its main international airport (e.g. Cameroon -> NSI, Japan -> HND).
    Do not leave the fields empty when the destination is recognizable.
    - Copy preferences ONLY from the fields and free text above; leave everything else null.

    TRAVEL MODE & MOBILITY (derive from free_text and structured fields):
    - travel_mode: one of 'fixed', 'road_trip', 'van_life', 'sailing', 'mixed' — deduce from how the user describes moving and sleeping in loco
    - accommodation_style: one of 'homestay', 'hotel', 'van', 'camping', 'boat', 'mixed' — must be consistent with travel_mode
    - mobility_preferences: list of means explicitly mentioned or strongly implied (auto, moto, bici, barca, trasporti_pubblici, a_piedi)
    """


def build_period_prompt(trip: TripResponse, intent: TripIntent, today_iso: str) -> str:
    return f"""The traveler gave no dates. Propose the best travel windows for this trip.

    Today is {today_iso}.
    Destination: {trip.destination or "not specified"}
    Interests: {', '.join(intent.interests) or 'not specified'}
    Style: {', '.join(intent.style) or 'not specified'}
    Travel mode: {intent.travel_mode or 'not specified'}
    Accommodation style: {intent.accommodation_style or 'not specified'}
    Mobility: {', '.join(intent.mobility_preferences) or 'not specified'}

    Consider the best season for the destination (climate, crowding, prices) and the traveler's interests, travel mode and mobility.
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
    Travel mode: {intent.travel_mode or 'not specified'}
    Accommodation style: {intent.accommodation_style or 'not specified'}
    Mobility: {', '.join(intent.mobility_preferences) or 'not specified'}

    EXPLORATION ANCHORS:
    {anchors_block}

    USER FREE TEXT (verbatim):
    "{trip.free_text}"

    Propose at most 4 targeted Google-Maps search queries (same language as the destination)
    that dig INTO the anchors along the brief's interests, style, travel mode and mobility —
    e.g. specific neighborhoods, niche venues, quiet alternatives, van-friendly spots,
    ports for sailing, campsites along routes. Each query must derive from an anchor.
    """


def build_curation_prompt(trip: TripResponse, intent: TripIntent, corpus_blocks: str) -> str:
    return f"""Select the best resources for this traveler from the numbered corpus below.

    TRIP CONTEXT:
    Interests: {', '.join(intent.interests) or 'not specified'}
    Style: {', '.join(intent.style) or 'not specified'}
    Pace: {intent.pace or 'not specified'}
    Travel mode: {intent.travel_mode or 'not specified'}
    Accommodation style: {intent.accommodation_style or 'not specified'}
    Mobility: {', '.join(intent.mobility_preferences) or 'not specified'}
    Destination: {trip.destination or 'not specified'}
    Departure: {trip.departure_location or 'not specified'}

    CORPUS (numbered with zero-based indices in brackets; reference ONLY these indices):
    {corpus_blocks}

    Rules: pick by merit for THIS brief — quality and fit, never filler. Zero items in a
    category is a valid choice when nothing fits. For travel_mode 'van_life' prefer van/camping
    stays; for 'sailing' prefer boat stays; for 'road_trip' prefer stops along route.
    IMPORTANT: For intercontinental or long-distance trips (different country/continent from departure),
    ALWAYS include at least one flight option if available. For 'fixed' travel_mode, flights are the
    primary way to reach the destination — prioritize them.
    Return zero-based indices only, plus a short Italian rationale.
    """


def build_geo_prompt(trip: TripResponse, intent: TripIntent) -> str:
    return f"""Resolve the geographic unknowns for this trip. Return BOTH resolutions in one answer.

    TRIP CONTEXT:
    Destination from the form: {trip.destination or "not specified"}
    Departure location from the form: {trip.departure_location or "not specified"}
    Interests: {', '.join(intent.interests) or 'not specified'}
    Style: {', '.join(intent.style) or 'not specified'}
    Pace: {intent.pace or 'not specified'}
    Travel mode: {intent.travel_mode or 'not specified'}
    Accommodation style: {intent.accommodation_style or 'not specified'}
    Mobility: {', '.join(intent.mobility_preferences) or 'not specified'}

    USER FREE TEXT (verbatim):
    "{trip.free_text}"

    PART 1 — ResolvedDestinations (region check):
    - If the destination is already a specific place, return it as the single ResolvedPlace
      with its main airport code.
    - If the destination is a country/region (or unspecified), pick AT MOST 2 concrete places
      (islands, cities) that fit this traveler's interests, style, pace, travel mode and mobility,
      considering the season implied by the trip dates and the brief. Each place gets its main IATA airport.
    - The rationale MUST be written in ITALIAN.

    PART 2 — DepartureAirports (departure expansion):
    - If the departure location is a city, region or country, list 1..4 candidate IATA codes
      for its main international airports (max 4).
    - If the departure location is not placeable, NEVER invent codes: return an empty list.

    Do not invent airport codes that do not exist.
    """


def build_email_prompt(
    intent: TripIntent,
    flights_block: str,
    maps_block: str,
    places_block: str,
    trip: TripResponse | None = None,
    resolve_rationale: str = "",
) -> str:
    return f"""Write the trip email for this traveler.

    TRIP CONTEXT (only these preferences exist — never invent others):
    Interests: {', '.join(intent.interests) or 'not specified'}
    Style sought: {', '.join(intent.style) or 'not specified'}
    Pace: {intent.pace or 'not specified'}
    Travel mode: {intent.travel_mode or 'not specified'}
    Accommodation style: {intent.accommodation_style or 'not specified'}
    Mobility: {', '.join(intent.mobility_preferences) or 'not specified'}
    Travelers count: {trip.travelers_count if trip else 'not specified'}
    Travelers type: {trip.travelers_type if trip else 'not specified'}
    Budget: {trip.budget_amount if trip else 'not specified'}
{f"\n    Focus scelto dal sistema: {resolve_rationale}\n" if resolve_rationale else ""}
    USER FREE TEXT (verbatim):
    "{trip.free_text if trip else ''}"

    RESOURCES AVAILABLE (IDs in brackets; cite ONLY these):
    Flights:
    {flights_block}

    Points of interest:
    {maps_block}

    Accommodation:
    {places_block}

    COMPOSITION RULES:
    - If travel_mode is 'road_trip' or 'van_life': include a "Come muoversi" section explaining the route logic, daily drives, overnight stops; do NOT list bare flight links if they don't fit the mode.
    - If travel_mode is 'sailing': include a "Navigazione" section with ports, charter info, coastal hops.
    - If accommodation_style is 'van' or 'camping': show overnight stops/campsites, not hotel cards.
    - NEVER print internal IDs like [M0], [P2] in the email — cite only bracket IDs from the RESOURCES above.
    - If mobility includes 'auto'/'moto'/'barca': weave a short practical paragraph about getting around locally.
    """