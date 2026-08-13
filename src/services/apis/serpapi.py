"""Shared SerpAPI client across integrations."""
import asyncio
import logging
import re

from serpapi import Client
from serpapi.exceptions import SerpApiError

from src.settings import get_settings

logger = logging.getLogger("nostos.serpapi")

_API_KEY_PATTERN = re.compile(r"api_key=[^&\s]+")


class SerpAPIError(Exception):
    """Application error for failed SerpAPI searches."""


def _redact(message: str) -> str:
    return _API_KEY_PATTERN.sub("api_key=***", message)


async def search(params: dict, timeout: float = 60.0, api_key: str | None = None, client: Client | None = None) -> dict:
    """Runs a SerpAPI search and returns the JSON, raising SerpAPIError on error."""
    logger.info(
        "serpapi: engine=%s %s",
        params.get("engine"),
        " ".join(f"{k}={v}" for k, v in params.items() if k != "engine"),
    )
    if client is None:
        client = Client(api_key=api_key or get_settings().serpapi_key)
    try:
        results = await asyncio.wait_for(asyncio.to_thread(client.search, params), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise SerpAPIError(f"timeout after {timeout}s on {params.get('engine')}") from exc
    except SerpApiError as exc:
        logger.warning("serpapi: HTTP error %s", _redact(str(exc)))
        raise SerpAPIError(_redact(str(exc))) from exc

    data = results.as_dict()
    if "error" in data:
        logger.warning("serpapi: JSON error %s", data["error"])
        raise SerpAPIError(data["error"])
    return data
