import argparse
import logging
import os

import asyncpg
from arq import Worker
from arq.connections import RedisSettings

from src.infrastructure.jobs import run_trip_job
from src.settings import get_settings

logger = logging.getLogger("nostos.worker")

QUEUE_NAME = "nostos"

MODEL_ENV_VARS = {
    "claude": "NOSTOS_CLAUDE_MODEL",
    "gpt": "NOSTOS_GPT_MODEL",
    "ollama": "NOSTOS_OLLAMA_MODEL",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="nostos-worker",
        description="Starts the Nostos worker that executes trip jobs from the queue.",
    )
    parser.add_argument("--claude", action="store_const", const="claude", dest="provider", help="Use Anthropic Claude")
    parser.add_argument("--gpt", action="store_const", const="gpt", dest="provider", help="Use OpenAI GPT")
    parser.add_argument("--ollama", action="store_const", const="ollama", dest="provider", help="Use a local Ollama model")
    parser.add_argument(
        "--serpapi-timeout",
        type=float,
        default=None,
        help="Timeout for each SerpAPI search, in seconds (default: from .env)",
    )
    parser.add_argument(
        "--email-timeout",
        type=float,
        default=None,
        help="Timeout for sending emails via Resend, in seconds (default: from .env)",
    )
    parser.add_argument(
        "--llm-timeout",
        type=float,
        default=None,
        help="Timeout for LLM calls, in seconds (default: from .env)",
    )
    parser.set_defaults(provider=None)
    return parser.parse_args()


def _apply_env_overrides(args: argparse.Namespace) -> None:
    if args.provider:
        os.environ["NOSTOS_LLM_PROVIDER"] = args.provider
    if args.serpapi_timeout is not None:
        os.environ["NOSTOS_SERPAPI_TIMEOUT"] = str(args.serpapi_timeout)
    if args.email_timeout is not None:
        os.environ["NOSTOS_EMAIL_TIMEOUT"] = str(args.email_timeout)
    if args.llm_timeout is not None:
        os.environ["NOSTOS_LLM_TIMEOUT"] = str(args.llm_timeout)
    get_settings.cache_clear()


def _assert_model_configured() -> None:
    """Fail fast when the configured provider has no model (misconfiguration)."""
    settings = get_settings()
    provider = settings.llm_provider
    model = getattr(settings, provider + "_model", "")
    if not model:
        env = MODEL_ENV_VARS[provider]
        raise SystemExit(f"LLM provider '{provider}' has no model: set {env} in .env")
    logger.info("LLM provider: %s, model: %s", provider, model)


async def startup(ctx: dict) -> None:
    settings = get_settings()
    ctx["pg_pool"] = await asyncpg.create_pool(settings.postgres_url)


async def shutdown(ctx: dict) -> None:
    await ctx["pg_pool"].close()


if __name__ == "__main__":
    from src.logging import setup_logging

    setup_logging()
    _apply_env_overrides(_parse_args())
    _assert_model_configured()
    settings = get_settings()
    worker = Worker(
        functions=[run_trip_job],
        on_startup=startup,
        on_shutdown=shutdown,
        redis_settings=RedisSettings.from_dsn(settings.redis_url),
        queue_name=QUEUE_NAME,
        max_jobs=10,
        max_tries=3,
        job_timeout=1800,
        keep_result=3600,
        poll_delay=0.5,
        retry_jobs=True,
    )
    worker.run()