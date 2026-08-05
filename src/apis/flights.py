"""APIs for handling flights lookup"""
import asyncio
import re
from typing import Optional

from serpapi import Client

from src.settings import get_settings

IATA_PATTERN = re.compile(r"\b([A-Z]{3})\b")


def _airport_code(value: str) -> str:
    """Estrae un codice IATA se presente nel testo, altrimenti usa il testo così com'è."""
    match = IATA_PATTERN.search(value)
    return match.group(1) if match else value


async def _search(params: dict) -> dict:
    settings = get_settings()
    client = Client(api_key=settings.serpapi_key)
    results = await asyncio.to_thread(client.search, params)
    return results.as_dict()


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

    data = await _search(params)
    if "error" in data:
        return []

    flights = data.get("best_flights", []) + data.get("other_flights", [])
    return [_normalize(f) for f in flights[:5]]
