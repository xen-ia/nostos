"""APIs for handling room/camping search"""
import asyncio
from datetime import date, timedelta
from typing import Optional

from serpapi import Client

from src.settings import get_settings


async def _search(params: dict) -> dict:
    settings = get_settings()
    client = Client(api_key=settings.serpapi_key)
    results = await asyncio.to_thread(client.search, params)
    return results.as_dict()


def _default_dates() -> tuple[str, str]:
    today = date.today()
    return (today + timedelta(days=14)).isoformat(), (today + timedelta(days=21)).isoformat()


def _normalize(property_: dict) -> dict:
    rate_per_night = property_.get("rate_per_night", {}) or {}
    total_rate = property_.get("total_rate", {}) or {}
    return {
        "name": property_.get("name", "N/D"),
        "type": property_.get("type", "N/D"),
        "price_per_night_eur": rate_per_night.get("extracted_lowest"),
        "total_price_eur": total_rate.get("extracted_lowest"),
        "essential_info": property_.get("essential_info"),
    }


async def search(destination: Optional[str], interests: list[str], style: list[str]) -> list[dict]:
    """Cerca alloggi su Google Hotels via SerpAPI."""
    if not destination:
        return []

    query = f"hotels in {destination}"
    if interests:
        query = f"hotels in {destination}: {interests[0]}"

    check_in, check_out = _default_dates()
    data = await _search(
        {
            "engine": "google_hotels",
            "q": query,
            "check_in_date": check_in,
            "check_out_date": check_out,
            "hl": "it",
            "gl": "it",
            "currency": "EUR",
        }
    )
    if "error" in data:
        return []

    properties = data.get("properties", [])
    return [_normalize(p) for p in properties[:5]]