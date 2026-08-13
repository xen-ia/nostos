# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.13-slim-bookworm AS runtime
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NOSTOS_HOST=0.0.0.0 \
    NOSTOS_PORT=3072

COPY --from=builder /app/.venv /app/.venv
COPY . .

RUN useradd --create-home --shell /usr/sbin/nologin nostos \
    && chown -R nostos:nostos /app
USER nostos

EXPOSE 3072

# Default: API server. The worker is started by overriding the command
# (e.g. `python -m src.worker`) in the platform's worker service.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3072"]
