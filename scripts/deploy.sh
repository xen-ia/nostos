#!/usr/bin/env bash
# Deploy nostos with Docker Compose on a self-hosted VM (Oracle Free Tier etc.).
# Usage: scripts/deploy.sh   (run from the repo root on the VM, `.env` already set)
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.prod.yml"

echo "==> Building images and starting postgres + redis..."
$COMPOSE up -d --build postgres redis

echo "==> Waiting for Postgres..."
until $COMPOSE exec -T postgres pg_isready -U nostos -d nostos >/dev/null 2>&1; do
    sleep 2
done

echo "==> Applying schema (idempotent)..."
$COMPOSE exec -T postgres psql -U nostos -d nostos < schema.sql

echo "==> Starting web + worker..."
$COMPOSE up -d --build

echo "==> Status:"
$COMPOSE ps
