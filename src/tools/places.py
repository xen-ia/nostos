"""APIs for handling room/camping search"""
from datetime import date, timedelta
from typing import Optional

from src.apis.serpapi import SerpAPIError, search as serpapi_search


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
        "link": property_.get("link"),
    }


async def search(
    destination: Optional[str],
    interests: list[str],
    style: list[str],
    check_in_date: Optional[str] = None,
    check_out_date: Optional[str] = None,
    timeout: float = 60.0,
) -> list[dict]:
    """Cerca alloggi su Google Hotels via SerpAPI."""
    if not destination:
        return []

    query = f"hotels in {destination}"
    if interests:
        query = f"hotels in {destination}: {interests[0]}"

    check_in, check_out = check_in_date, check_out_date
    if not check_in or not check_out:
        check_in, check_out = _default_dates()
    try:
        data = await serpapi_search(
            {
                "engine": "google_hotels",
                "q": query,
                "check_in_date": check_in,
                "check_out_date": check_out,
                "hl": "it",
                "gl": "it",
                "currency": "EUR",
            },
            timeout=timeout,
        )
    except SerpAPIError:
        return []

    properties = data.get("properties", [])
    return [_normalize(p) for p in properties[:5]]
