"""APIs for handling room/camping search"""
from datetime import date, timedelta
from typing import Optional

from src.services.apis.serpapi import search as serpapi_search
from src.services.tools._util import dedupe_cap


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
    *,
    destination: Optional[str],
    check_in_date: Optional[str] = None,
    check_out_date: Optional[str] = None,
    query: Optional[str] = None,
    timeout: float = 60.0,
    api_key: str | None = None,
) -> list[dict]:
    """Searches accommodations on Google Hotels via SerpAPI."""
    if not destination:
        return []

    query = query or f"hotels in {destination}"

    check_in, check_out = check_in_date, check_out_date
    if not check_in or not check_out:
        check_in, check_out = _default_dates()
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
        api_key=api_key,
    )

    properties = [_normalize(p) for p in data.get("properties", [])]
    linked = [p for p in properties if p.get("link")]
    return dedupe_cap(linked, cap=8)
