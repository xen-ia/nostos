"""APIs for handling flights lookup"""
import re
from typing import Optional

from src.apis.serpapi import SerpAPIError, search as serpapi_search

IATA_PATTERN = re.compile(r"^[A-Z]{3}$")


def _airport_code(value: str) -> Optional[str]:
    """Ritorna il codice IATA se il testo è un codice di 3 lettere, altrimenti None."""
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
) -> list[dict]:
    """Cerca voli su Google Flights via SerpAPI."""
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

    try:
        data = await serpapi_search(params, timeout=timeout)
    except SerpAPIError:
        return []

    link = data.get("search_metadata", {}).get("google_flights_url")
    flights = data.get("best_flights", []) + data.get("other_flights", [])
    return [_normalize(f, link) for f in flights[:5]]
