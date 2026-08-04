"""APIs for handling flights lookup"""
from typing import Optional


async def search(
    departure: Optional[str],
    destination: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
) -> list[dict]:
    """Stub: dati finti ma plausibili, sostituito da un provider reale in seguito."""
    return [
        {
            "airline": "ITA Airways",
            "from": departure or "N/D",
            "to": destination or "destinazione da definire",
            "departure_date": start_date,
            "return_date": end_date,
            "price_eur": 187,
        },
    ]