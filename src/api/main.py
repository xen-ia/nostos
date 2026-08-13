from contextlib import asynccontextmanager
import time

import asyncpg
import redis.asyncio as redis_async
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from src.settings import get_settings
from src.api.routers import trips
from src.api.errors import register_exception_handlers
from src.logging import setup_logging
from src.api.middleware import RequestIDMiddleware

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.trips_created = 0
    app.state.redis = redis_async.from_url(settings.redis_url, decode_responses=True)
    app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    app.state.pg_pool = await asyncpg.create_pool(settings.postgres_url)

    yield

    await app.state.redis.aclose()
    await app.state.arq.aclose()
    await app.state.pg_pool.close()


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(trips.router)

START_TIME = time.time()


def add_health_routes(application: FastAPI) -> None:
    @application.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @application.get("/readyz")
    async def readyz(request: Request) -> JSONResponse:
        checks = {}
        try:
            await request.app.state.redis.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "unreachable"
        try:
            async with request.app.state.pg_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            checks["postgres"] = "ok"
        except Exception:
            checks["postgres"] = "unreachable"
        ready = all(v == "ok" for v in checks.values())
        return JSONResponse(
            {"status": "ready" if ready else "degraded", "checks": checks},
            status_code=200 if ready else 503,
        )

    @application.get("/metrics")
    async def metrics(request: Request) -> PlainTextResponse:
        uptime_s = int(time.time() - START_TIME)
        created = getattr(application.state, "trips_created", 0)
        done = error = 0
        try:
            rows = await request.app.state.pg_pool.fetch(
                "SELECT status, COUNT(*) AS n FROM trip_history GROUP BY status"
            )
            counts = {r["status"]: r["n"] for r in rows}
            done = int(counts.get("done", 0))
            error = int(counts.get("error", 0))
            created = int(counts.get("pending", 0)) + int(counts.get("running", 0)) + done + error
        except Exception:
            pass
        body = (
            f"nostos_uptime_seconds {uptime_s}\n"
            f"nostos_trips_created_total {created}\n"
            f"nostos_trips_done_total {done}\n"
            f"nostos_trips_error_total {error}\n"
        )
        return PlainTextResponse(body, media_type="text/plain; version=0.0.4")


add_health_routes(app)


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("src.api.main:app", host=settings.host, port=settings.port, reload=settings.reload)


if __name__ == "__main__":
    run()