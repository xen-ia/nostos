"""Client SerpAPI condiviso tra le integrazioni."""
import asyncio
import logging

from serpapi import Client
from serpapi.exceptions import SerpApiError

from src.settings import get_settings

logger = logging.getLogger("nostos.serpapi")


class SerpAPIError(Exception):
    """Errore applicativo per le ricerche SerpAPI fallite."""


async def search(params: dict) -> dict:
    """Esegue una ricerca SerpAPI e ritorna il JSON, alzando SerpAPIError in caso di errore."""
    logger.info("serpapi: engine=%s params=%s", params.get("engine"), params)
    settings = get_settings()
    client = Client(api_key=settings.serpapi_key)
    try:
        results = await asyncio.to_thread(client.search, params)
    except SerpApiError as exc:
        logger.warning("serpapi: errore HTTP %s", exc)
        raise SerpAPIError(str(exc)) from exc

    data = results.as_dict()
    if "error" in data:
        logger.warning("serpapi: errore nel JSON %s", data["error"])
        raise SerpAPIError(data["error"])
    return data
