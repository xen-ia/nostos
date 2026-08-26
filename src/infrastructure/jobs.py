import logging

import redis.asyncio as redis_async

from src.services.apis.email import EmailSender
from src.services.apis.llm import build_llm_client
from src.infrastructure.database import Database
from src.infrastructure.version import get_app_version
from src.core.orchestrator import TripOrchestrator
from src.settings import get_settings
from src.services.trip_store import TripStore

logger = logging.getLogger("nostos.jobs")


async def run_trip_job(ctx: dict, trip_id: str) -> None:
    """ARQ job: run the trip pipeline for a trip_id."""
    settings = get_settings()
    redis = redis_async.from_url(settings.redis_url, decode_responses=True)
    try:
        store = TripStore(redis=redis, ttl_seconds=settings.redis_job_ttl_seconds)
        llm = build_llm_client(settings)
        email_sender = EmailSender(
            api_key=settings.resend_api_key,
            from_address=settings.email_from_address,
        )
        database = Database(pool=ctx["pg_pool"])

        orchestrator = TripOrchestrator(
            store=store,
            llm_client=llm,
            email_sender=email_sender,
            database=database,
            trip_id=trip_id,
            serpapi_timeout=settings.serpapi_timeout,
            email_timeout=settings.email_timeout,
            serpapi_api_key=settings.serpapi_key or None,
            llm_model=_active_model(settings),
            app_version=get_app_version(),
        )
        await orchestrator.run()
    finally:
        await redis.aclose()


def _active_model(settings) -> str:
    provider = settings.llm_provider
    if provider == "gpt":
        return settings.gpt_model
    if provider == "ollama":
        return settings.ollama_model
    return settings.claude_model
