import asyncpg
from arq.connections import ArqRedis
from fastapi import Depends, Request
from redis.asyncio import Redis

from src.services.apis.email import EmailSender
from src.services.apis.llm import LLMClient, build_llm_client
from src.infrastructure.database import Database
from src.settings import Settings, get_settings
from src.services.trip_store import TripStore


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_arq(request: Request) -> ArqRedis:
    return request.app.state.arq


def get_trip_store(
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> TripStore:
    return TripStore(redis=redis, ttl_seconds=settings.redis_job_ttl_seconds)


def get_llm_client(
    settings: Settings = Depends(get_settings),
) -> LLMClient:
    return build_llm_client(settings)


def get_email_sender(settings: Settings = Depends(get_settings)) -> EmailSender:
    return EmailSender(api_key=settings.resend_api_key, from_address=settings.email_from_address)


def get_serpapi_timeout(settings: Settings = Depends(get_settings)) -> float:
    return settings.serpapi_timeout


def get_email_timeout(settings: Settings = Depends(get_settings)) -> float:
    return settings.email_timeout


def get_serpapi_key(settings: Settings = Depends(get_settings)) -> str | None:
    return settings.serpapi_key or None


def get_postgres(request: Request) -> asyncpg.Pool:
    return request.app.state.pg_pool


def get_database(pool: asyncpg.Pool = Depends(get_postgres)) -> Database:
    return Database(pool=pool)