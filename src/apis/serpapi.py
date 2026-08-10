"""Shared SerpAPI client across integrations."""
import asyncio
import logging

from serpapi import Client
from serpapi.exceptions import SerpApiError

from src.settings import get_settings

logger = logging.getLogger("nostos.serpapi")


class SerpAPIError(Exception):
    """Application error for failed SerpAPI searches."""


async def search(params: dict, timeout: float = 60.0) -> dict:
    """Runs a SerpAPI search and returns the JSON, raising SerpAPIError on error."""
    logger.info("serpapi: engine=%s params=%s", params.get("engine"), params)
    settings = get_settings()
    client = Client(api_key=settings.serpapi_key)
    try:
        results = await asyncio.wait_for(asyncio.to_thread(client.search, params), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise SerpAPIError(f"timeout after {timeout}s on {params.get('engine')}") from exc
    except SerpApiError as exc:
        logger.warning("serpapi: HTTP error %s", exc)
        raise SerpAPIError(str(exc)) from exc

    data = results.as_dict()
    if "error" in data:
        logger.warning("serpapi: JSON error %s", data["error"])
        raise SerpAPIError(data["error"])
    return data
