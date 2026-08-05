"""APIs for handling maps research"""
import asyncio
from typing import Optional

from serpapi import Client

from src.settings import get_settings


async def _search(params: dict) -> dict:
    settings = get_settings()
    client = Client(api_key=settings.serpapi_key)
    results = await asyncio.to_thread(client.search, params)
    return results.as_dict()


def _normalize(place: dict) -> dict:
    return {
        "name": place.get("title", "N/D"),
        "type": place.get("type", "N/D"),
        "rating": place.get("rating"),
        "reviews_count": place.get("reviews"),
        "address": place.get("address"),
        "description": place.get("description"),
    }


async def research(destination: Optional[str], interests: list[str]) -> list[dict]:
    """Cerca punti di interesse su Google Maps via SerpAPI."""
    if not destination:
        return []

    query = f"points of interest in {destination}"
    if interests:
        query = f"{interests[0]} in {destination}"

    data = await _search(
        {
            "engine": "google_maps",
            "q": query,
            "type": "search",
            "hl": "it",
        }
    )
    if "error" in data:
        return []

    places = data.get("local_results", [])
    return [_normalize(p) for p in places[:5]]
