import asyncpg
from fastapi import Depends, Request
from redis.asyncio import Redis

from src.apis.email import EmailSender
from src.apis.llm import AnthropicClient, LLMClient, OllamaClient, OpenAIClient
from src.database import Database
from src.prompts import SYSTEM_PROMPT
from src.settings import Settings, get_settings
from src.trip_store import TripStore


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_trip_store(
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> TripStore:
    return TripStore(redis=redis, ttl_seconds=settings.redis_job_ttl_seconds)


def get_llm_client(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> LLMClient:
    provider = request.app.state.llm_provider
    if provider == "gpt":
        return OpenAIClient(
            api_key=settings.openai_api_key,
            model=settings.gpt_model,
            system_prompt=SYSTEM_PROMPT,
        )
    if provider == "ollama":
        return OllamaClient(
            model=settings.ollama_model,
            system_prompt=SYSTEM_PROMPT,
            base_url=settings.ollama_url,
        )
    return AnthropicClient(
        api_key=settings.anthropic_api_key,
        model=settings.claude_model,
        system_prompt=SYSTEM_PROMPT,
    )


def get_email_sender(settings: Settings = Depends(get_settings)) -> EmailSender:
    return EmailSender(api_key=settings.resend_api_key, from_address=settings.email_from_address)


def get_serpapi_timeout(request: Request) -> float:
    return request.app.state.serpapi_timeout


def get_email_timeout(request: Request) -> float:
    return request.app.state.email_timeout


def get_postgres(request: Request) -> asyncpg.Pool:
    return request.app.state.pg_pool


def get_database(pool: asyncpg.Pool = Depends(get_postgres)) -> Database:
    return Database(pool=pool)