"""APIs for handling maps research"""
from typing import Optional


async def research(destination: Optional[str], interests: list[str]) -> list[dict]:
    """Stub: punti di interesse finti, coerenti con gli interessi passati."""
    return [
        {"name": f"Zona esplorabile a piedi vicino a {destination or 'la destinazione'}", "tags": interests}
    ]