"""Shared SerpAPI client across integrations."""
import asyncio
import hashlib
import json
import logging
import re

from serpapi import Client
from serpapi.exceptions import SerpApiError

from src.settings import get_settings

logger = logging.getLogger("nostos.serpapi")

_API_KEY_PATTERN = re.compile(r"api_key=[^&\s]+")

#: Cache TTL per engine (seconds): slow-moving POI/hotel data days, flights hours.
ENGINE_CACHE_TTL = {
    "google_maps": 7 * 86400,
    "google_hotels": 7 * 86400,
    "google_flights": 6 * 3600,
}

_cache_redis = None


def _cache_key(params: dict) -> str:
    stable = {k: v for k, v in sorted(params.items()) if k != "api_key"}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()
    return f"serpapi:{params.get('engine', 'unknown')}:{digest}"


async def _cache_client():
    """Lazy Redis client for the cache; None when unreachable (fail-open)."""
    global _cache_redis
    if _cache_redis is not None:
        return _cache_redis
    try:
        import redis.asyncio as redis

        client = redis.from_url(get_settings().redis_url, socket_connect_timeout=1)
        await client.ping()
        _cache_redis = client
    except Exception as exc:  # noqa: BLE001 — no cache is a valid state
        logger.debug("serpapi cache unavailable: %s", type(exc).__name__)
        _cache_redis = False
    return _cache_redis or None


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
    redis_client = None
    ttl = ENGINE_CACHE_TTL.get(params.get("engine", ""))
    if ttl:
        redis_client = await _cache_client()
        if redis_client is not None:
            try:
                cached = await redis_client.get(_cache_key(params))
                if cached:
                    logger.info("serpapi: cache hit engine=%s", params.get("engine"))
                    return json.loads(cached)
            except Exception as exc:  # noqa: BLE001 — cache reads never fail searches
                logger.debug("serpapi cache read failed: %s", type(exc).__name__)
                redis_client = None
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
    if redis_client is not None and ttl:
        try:
            await redis_client.setex(_cache_key(params), ttl, json.dumps(data, default=str))
        except Exception as exc:  # noqa: BLE001 — cache writes never fail searches
            logger.debug("serpapi cache write failed: %s", type(exc).__name__)
    return data
