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

echo "==> Syncing email whitelist from NOSTOS_WHITELIST_EMAILS..."
python3 - "$COMPOSE" <<'PY'
import json
import re
import subprocess
import sys

compose = sys.argv[1]

value = ""
try:
    with open(".env", encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"\s*NOSTOS_WHITELIST_EMAILS\s*=\s*(.*)$", line)
            if m:
                value = m.group(1).strip().strip('"').strip("'")
                break
except FileNotFoundError:
    pass

if not value:
    print("WARNING: NOSTOS_WHITELIST_EMAILS not set in .env, skipping whitelist sync")
    sys.exit(0)

try:
    emails = [e.strip().lower() for e in json.loads(value)]
except json.JSONDecodeError as exc:
    print(f"WARNING: NOSTOS_WHITELIST_EMAILS is not a valid JSON list, skipping sync ({exc})")
    sys.exit(0)

psql = compose.split() + ["exec", "-T", "postgres", "psql", "-U", "nostos", "-d", "nostos"]

def run(sql):
    subprocess.run(psql + ["-c", sql], check=True)

# Add new emails from the env registry (idempotent). Manual INSERTs in the
# table are intentionally left untouched, so removals happen manually too.
for email in emails:
    run(f"INSERT INTO email_whitelist (email) VALUES ('{email}') ON CONFLICT (email) DO NOTHING")

print(f"Whitelist synced from env: {len(emails)} email(s) ensured present (manual rows kept)")
PY

echo "==> Starting web + worker..."
$COMPOSE up -d --build

echo "==> Status:"
$COMPOSE ps

echo "==> Pruning dangling images and build cache..."
docker image prune -f >/dev/null 2>&1 || true
docker builder prune -f >/dev/null 2>&1 || true
