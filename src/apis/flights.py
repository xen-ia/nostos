"""APIs for handling flights lookup"""
import re
from typing import Optional

from src.apis.serpapi import SerpAPIError, search as serpapi_search

IATA_PATTERN = re.compile(r"\b([A-Z]{3})\b")


def _airport_code(value: str) -> str:
    """Estrae un codice IATA se presente nel testo, altrimenti usa il testo così com'è."""
    match = IATA_PATTERN.search(value)
    return match.group(1) if match else value


def _normalize(flight: dict) -> dict:
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
    }


async def search(
    departure: Optional[str],
    destination: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
) -> list[dict]:
    """Cerca voli su Google Flights via SerpAPI."""
    if not (departure and destination and start_date):
        return []

    params: dict = {
        "engine": "google_flights",
        "departure_id": _airport_code(departure),
        "arrival_id": _airport_code(destination),
        "outbound_date": start_date,
        "type": 1 if end_date else 2,
        "currency": "EUR",
        "hl": "it",
    }
    if end_date:
        params["return_date"] = end_date

    try:
        data = await serpapi_search(params)
    except SerpAPIError:
        return []

    flights = data.get("best_flights", []) + data.get("other_flights", [])
    return [_normalize(f) for f in flights[:5]]
