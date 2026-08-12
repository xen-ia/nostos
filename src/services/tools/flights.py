"""APIs for handling flights lookup"""
import re
from typing import Optional

from src.services.apis.serpapi import search as serpapi_search

IATA_PATTERN = re.compile(r"^[A-Z]{3}$")


def _airport_code(value: str) -> Optional[str]:
    """Returns the IATA code if the text is a 3-letter code, otherwise None."""
    match = IATA_PATTERN.match(value.strip())
    return match.group(0) if match else None


def _normalize(flight: dict, link: str | None = None) -> dict:
    legs = flight.get("flights", [])
    outbound = legs[0] if legs else {}
    return {
        "airline": outbound.get("airline", "N/D"),
        "from": outbound.get("departure_airport", {}).get("id", "N/D"),
        "to": legs[-1].get("arrival_airport", {}).get("id", "N/D") if legs else "N/D",
        "departure_date": outbound.get("departure_airport", {}).get("time", "N/D"),
        "return_date": None,
        "price_eur": flight.get("price"),
        "total_duration_minutes": flight.get("total_duration"),
        "link": link,
    }


async def search(
    departure: Optional[str],
    destination: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
    timeout: float = 60.0,
    api_key: str | None = None,
) -> list[dict]:
    """Searches flights on Google Flights via SerpAPI."""
    departure_code = _airport_code(departure)
    arrival_code = _airport_code(destination)
    if not (departure_code and arrival_code and start_date):
        return []

    params: dict = {
        "engine": "google_flights",
        "departure_id": departure_code,
        "arrival_id": arrival_code,
        "outbound_date": start_date,
        "type": 1 if end_date else 2,
        "currency": "EUR",
        "hl": "it",
    }
    if end_date:
        params["return_date"] = end_date

    data = await serpapi_search(params, timeout=timeout, api_key=api_key)

    link = data.get("search_metadata", {}).get("google_flights_url")
    flights = data.get("best_flights", []) + data.get("other_flights", [])
    return [_normalize(f, link) for f in flights[:5]]


# TODO: Implementare ricerca libera: non 5 ricerche uguali, 
# ma sondare più ricerche, da più angoli; cercare voli da più partenze 
# e scegliere il più economico