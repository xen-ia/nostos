import redis.asyncio as redis_async

redis_client = redis_async.from_url("redis://localhost:6379/0", decode_responses=True)