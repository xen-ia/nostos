import redis.asyncio as redis_async

from src.core.config import get_settings

settings = get_settings()

redis_client = redis_async.from_url(settings.redis_url, decode_responses=True)