import secrets
import time

import redis.asyncio as redis_async
from fastapi import Request

from src.api.errors import APIError, ErrorCode
from src.settings import Settings


class RateLimiter:
    """Sliding-window rate limiter backed by Redis (INCR + EXPIRE per key)."""

    def __init__(self, redis: redis_async.Redis, max_requests: int, window_seconds: int):
        self._redis = redis
        self._max = max_requests
        self._window = window_seconds

    async def check(self, key: str) -> None:
        redis_key = f"rl:{key}"
        try:
            count = await self._redis.incr(redis_key)
            if count == 1:
                await self._redis.expire(redis_key, self._window)
            if count > self._max:
                raise APIError(
                    ErrorCode.RATE_LIMITED,
                    f"Too many requests, retry later (limit {self._max}/{self._window}s)",
                    429,
                    headers={"Retry-After": str(self._window)},
                )
        except APIError:
            raise
        except redis_async.RedisError:
            # Fail-open: if Redis is down we must not brick the whole API.
            return


def build_rate_limiter(request: Request) -> RateLimiter:
    settings: Settings = request.app.state.settings
    return RateLimiter(
        request.app.state.redis,
        max_requests=settings.rate_limit_max,
        window_seconds=settings.rate_limit_window_seconds,
    )


def require_api_token(request: Request) -> None:
    """Bearer-token auth, enforced only when NOSTOS_API_TOKEN is configured."""
    settings: Settings = request.app.state.settings
    if not settings.api_token:
        return
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip() if auth else ""
    if not token or not secrets.compare_digest(token, settings.api_token):
        raise APIError(ErrorCode.UNAUTHORIZED, "Missing or invalid API token", 401)


def rate_limit_key(request: Request) -> str:
    """Rate-limit key: per-IP, or per-token when authenticated."""
    settings: Settings = request.app.state.settings
    auth = request.headers.get("Authorization", "")
    if auth and settings.api_token and auth.removeprefix("Bearer ").strip():
        return f"token:{auth.removeprefix('Bearer ').strip()}"
    client = request.client.host if request.client else "unknown"
    return f"ip:{client}"
