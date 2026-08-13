"""Backwards-compatible entry point: `uv run main.py` or `uvicorn main:app`.

The real FastAPI application lives in `src.api.main`.
"""
from src.api.main import add_health_routes, app, run

__all__ = ["app", "add_health_routes", "run"]


if __name__ == "__main__":
    run()