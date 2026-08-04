"""APIs for handling room/camping search"""
from typing import Optional


async def search(destination: Optional[str], interests: list[str], style: list[str]) -> list[dict]:
    """Stub: alloggi/esperienze finti, orientati allo stile di viaggio."""
    return [
        {
            "name": "Agriturismo locale (esempio)",
            "type": "alloggio autentico",
            "matches_style": style,
        }
    ]