from contextlib import asynccontextmanager
import argparse
import logging

import asyncpg
import redis.asyncio as redis_async
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from rich.logging import RichHandler

from src.settings import get_settings
from src.routers import trips

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="%H:%M:%S",
    handlers=[RichHandler(rich_tracebacks=True, show_time=True, show_path=True, markup=True)],
)

settings = get_settings()

logger = logging.getLogger("nostos")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="nostos",
        description="Avvia il backend Nostos. Seleziona il provider LLM da usare.",
    )
    parser.add_argument("--claude", action="store_const", const="claude", dest="provider", help="Usa Anthropic Claude")
    parser.add_argument("--gpt", action="store_const", const="gpt", dest="provider", help="Usa OpenAI GPT")
    parser.add_argument("--ollama", action="store_const", const="ollama", dest="provider", help="Usa Ollama locale")
    parser.add_argument(
        "--serpapi-timeout",
        type=float,
        default=60.0,
        help="Timeout di ogni ricerca SerpAPI, in secondi (default: 60)",
    )
    parser.add_argument(
        "--email-timeout",
        type=float,
        default=60.0,
        help="Timeout dell'invio email via Resend, in secondi (default: 60)",
    )
    parser.set_defaults(provider="claude")
    return parser.parse_args()


ARGS = _parse_args()
PROVIDER = ARGS.provider
SERPAPI_TIMEOUT = ARGS.serpapi_timeout
EMAIL_TIMEOUT = ARGS.email_timeout

PROVIDER_MODELS = {
    "claude": settings.claude_model,
    "gpt": settings.gpt_model,
    "ollama": settings.ollama_model,
}

MODEL_ENV_VARS = {
    "claude": "NOSTOS_CLAUDE_MODEL",
    "gpt": "NOSTOS_GPT_MODEL",
    "ollama": "NOSTOS_OLLAMA_MODEL",
}


def _fail_fast() -> None:
    if not PROVIDER_MODELS[PROVIDER]:
        raise SystemExit(
            f"Provider LLM '{PROVIDER}' senza modello: definisci {MODEL_ENV_VARS[PROVIDER]} nel .env"
        )


_fail_fast()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.llm_provider = PROVIDER
    app.state.serpapi_timeout = SERPAPI_TIMEOUT
    app.state.email_timeout = EMAIL_TIMEOUT
    logger.info("LLM provider: %s — modello: %s", PROVIDER, PROVIDER_MODELS[PROVIDER])
    logger.info("SerpAPI timeout: %.1fs", SERPAPI_TIMEOUT)
    logger.info("Email timeout: %.1fs", EMAIL_TIMEOUT)
    app.state.redis = redis_async.from_url(settings.redis_url, decode_responses=True)
    app.state.pg_pool = await asyncpg.create_pool(settings.postgres_url)

    yield

    await app.state.redis.aclose()
    await app.state.pg_pool.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(trips.router)


def run() -> None:
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=settings.reload)


if __name__ == "__main__":
    run()