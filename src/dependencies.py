from fastapi import Depends, Request
from redis.asyncio import Redis
import asyncpg

from src.apis.llm import AnthropicClient, LLMClient
from src.settings import Settings, get_settings
from src.trip_store import TripStore
from src.apis.email import EmailSender
from src.database import Database


def get_postgres(request: Request) -> asyncpg.Pool:
    return request.app.state.pg_pool


def get_database(pool: asyncpg.Pool = Depends(get_postgres)) -> Database:
    return Database(pool=pool)


def get_email_sender(settings: Settings = Depends(get_settings)) -> EmailSender:
    return EmailSender(api_key=settings.resend_api_key, from_address=settings.email_from_address)


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_trip_store(
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> TripStore:
    return TripStore(redis=redis, ttl_seconds=settings.redis_job_ttl_seconds)


def get_llm_client(settings: Settings = Depends(get_settings)) -> LLMClient:
    return AnthropicClient(api_key=settings.anthropic_api_key, model=settings.llm_model)