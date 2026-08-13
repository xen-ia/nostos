"""APIs for handling maps research"""
from typing import Optional

from src.services.apis.serpapi import search as serpapi_search


def _normalize(place: dict) -> dict:
    return {
        "name": place.get("title", "N/D"),
        "type": place.get("type", "N/D"),
        "rating": place.get("rating"),
        "reviews_count": place.get("reviews"),
        "address": place.get("address"),
        "description": place.get("description"),
        "link": place.get("website"),
    }


async def research(destination: Optional[str], interests: list[str], timeout: float = 60.0, api_key: str | None = None) -> list[dict]:
    """Searches points of interest on Google Maps via SerpAPI."""
    if not destination:
        return []

    query = f"points of interest in {destination}"
    if interests:
        query = f"{interests[0]} in {destination}"

    data = await serpapi_search(
        {
            "engine": "google_maps",
            "q": query,
            "type": "search",
            "hl": "it",
        },
        timeout=timeout,
        api_key=api_key,
    )

    places = data.get("local_results", [])
    return [_normalize(p) for p in places[:5]]
