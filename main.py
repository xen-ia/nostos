from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as redis_async
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.settings import get_settings
from src.routers import trips

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
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