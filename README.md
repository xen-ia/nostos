# νόστος-ξενία

```md
nostos/
├── main.py                    # shim: uv run main.py → src/api/main.py
├── schema.sql
├── Dockerfile
├── docs/
│   └── index.html
└── src/
    ├── api/                   # web layer (FastAPI)
    │   ├── main.py
    │   ├── dependencies.py
    │   ├── errors.py
    │   ├── middleware.py
    │   ├── security.py
    │   └── routers/trips.py
    ├── core/                  # domain: orchestration + LLM schemas + DTOs
    │   ├── orchestrator.py
    │   ├── models.py
    │   ├── schemas.py
    │   └── prompts/
    ├── services/              # external integrations
    │   ├── apis/              # llm, email, serpapi
    │   ├── tools/             # flights, maps, places
    │   ├── templates/
    │   └── trip_store.py
    ├── infrastructure/        # storage + queue
    │   ├── database.py
    │   ├── jobs.py
    │   ├── worker.py
    │   └── queue.py
    ├── settings.py
    └── logging.py
```

### Quickstart
Fill in your API keys for the models (`anthropic` and/or `openai`) and for the services (`resend`, `serpapi`) — the latter offers a usable free plan.
```bash
cp .env.example .env
```

Then run the server **and** the worker (the worker is what actually executes trips; both read all config from `.env`):
```bash
uv run main.py
uv run python -m src.infrastructure.worker
```

You can override provider and timeouts from the CLI on the worker (the process that uses them):
```bash
uv run python -m src.infrastructure.worker --gpt --serpapi-timeout 180 --email-timeout 180 --llm-timeout 120
```

and send a request from the mock frontend at [https://xen-ia.github.io/nostos/](https://xen-ia.github.io/nostos/).

#### CLI Test
Instead, you can test locally by sending a curl request
```bash
curl -s -X POST http://localhost:3072/api/v1/trips \
  -H 'Content-Type: application/json' \
  -d '{
    "email": "tesei.edoardo997@gmail.com",
    "destination": "Crete",
    "departure_location": "Italy",
    "start_date": "2027-07-30",
    "end_date": "2027-08-30",
    "flexible_dates": false,
    "travelers_count": 2,
    "travelers_type": "coppia",
    "budget_range": "medio",
    "free_text": "cibo e tradizioni locali, mare e relax, ritmo lento, lontano dalle folle. Vorrei fare una vacanza in road trip: noleggiare un van/jeep e dormire lungo il percorso"
  }'
```
or
```bash
curl -s -X POST http://localhost:3072/api/v1/trips \
  -H 'Content-Type: application/json' \
  -d '{
    "email": "tesei.edoardo997@gmail.com",
    "destination": "Hawaaii",
    "departure_location": "Italy",
    "start_date": null,
    "end_date": null,
    "flexible_dates": true,
    "travelers_count": 1,
    "travelers_type": null,
    "budget_range": "medio",
    "free_text": "Viaggi in barca, conoscere la cultura indigena locale. Poké, cibo e tradizioni locali, mare e relax, ritmo lento, lontano dalle folle."
  }'
```

## Architecture

### Core fundamentals
- `src/api/main.py` — FastAPI entrypoint (root `main.py` is a thin shim). The LLM provider and timeouts are configured via `.env`; the worker executes the pipeline.
- `src/core/orchestrator.py` — `TripOrchestrator`: extracts the intent via LLM → gathers flights/POIs/accommodations from SerpAPI → composes and sends the email.
- `src/services/apis/` — external providers: `llm.py` (protocol + Anthropic/OpenAI/Ollama clients), `email.py` (Resend), `serpapi.py` (shared client).
- `src/services/tools/` — pipeline capabilities: pydantic extraction schema (`__init__.py`) and `flights`/`maps`/`places` searches.
- `src/core/prompts/system_prompt.md` — Xen-IA editorial voice, the single source of rules for the models.
- `src/api/routers/trips.py` — REST API under `/api/v1`: `POST /trips` (202 + `Location`, enqueues an ARQ job), `GET /trips/{id}` (status), `POST /trips/{id}/feedback` (201).
- `src/infrastructure/jobs.py` / `worker.py` / `queue.py` — ARQ job queue: `POST /trips` only enqueues; a separate worker process runs the pipeline.
- `schema.sql` — Postgres schema: `trip_history` (status + email history) and `feedback` (ratings).
- `docs/index.html` — mock frontend

### System design

Flow (in the background after `POST /trips`): form → `TripStore` (Redis) → intent extraction via LLM → SerpAPI searches (flights/POIs/accommodations) → email composition via LLM → Resend send → Postgres history.

- **FastAPI (`src/api/main.py`)** — API + lifespan (Redis/Postgres connections). All config (provider, timeouts) comes from `.env`; the worker runs the pipeline.
- **Redis** — trip job store: creation, status (`PENDING`/`RUNNING`/`ERROR`/…) and atomic `SET NX EX` lock against double execution.
- **Postgres** — `trip_history`: history of sent emails (intent, searched package, subject/body) + `feedback`; schema in `schema.sql`.
- **LLM (`LLMClient` protocol)** — structured extraction via tool-call on pydantic models (`TripIntent`, `EmailContent`). Implementations: `AnthropicClient`, `OpenAIClient` (Responses API), `OllamaClient`; provider/model chosen via `.env` (overridable on the worker CLI).
- **SerpAPI** — searches flights (`google_flights`), POIs (`google_maps`), accommodations (`google_hotels`), with a configurable timeout; the engine and its input params are logged. Category without valid results → discarded; if all are empty, the trip stops without sending the email.
- **Resend** — transactional email sending (`EmailSender`), configurable timeout.
- **Prompts (`system_prompt.md`)** — Xen-IA editorial voice, the single source of rules; per-task prompts only bring in the data context.

## Deploy (Railway)

The repo ships a production Dockerfile (`Dockerfile`, non-root, uv-built). Railway is the
simplest target: it provisions Postgres and Redis as managed addons and deploys from GitHub.

1. **Provision infra** (Railway dashboard): create a Postgres addon and a Redis addon.
2. **Deploy the app**: connect the repo, Railway builds the Dockerfile automatically.
   Apply the schema once: `psql "$RAILWAY_POSTGRES_URL" < schema.sql` (no migration tooling yet).
3. **Set env vars** on the app service (from `.env.example`, all `NOSTOS_` prefixed):
   `NOSTOS_REDIS_URL`, `NOSTOS_POSTGRES_URL`, `NOSTOS_ANTHROPIC_API_KEY`,
   `NOSTOS_SERPAPI_KEY`, `NOSTOS_RESEND_API_KEY`, `NOSTOS_API_TOKEN`,
   `NOSTOS_ALLOWED_ORIGINS` (JSON list of frontend origins).
4. **Add a second service** for the worker: same repo/build, but the start command is
   `python -m src.infrastructure.worker`. It shares the same env vars.
5. **Health checks**: Railway uses `/healthz` (liveness) and `/readyz` (readiness;
   200 only when Redis and Postgres respond). `/metrics` exposes Prometheus counters.

The API and worker are two services running the same image — no extra orchestration.

## Deploy (self-hosted VM — Oracle Cloud Free Tier)

Same Dockerfile, run on any ARM64/x86_64 VM with Docker. The full stack runs
inside one Compose project — no managed addons needed.

1. **Create a VM** (e.g. Oracle Always Free Ampere A1, 2 OCPU / 12 GB, Ubuntu
   24.04 ARM). Open only ports `22` (SSH) and `80` (HTTP for the Cloudflare
   proxy) in the VCN security list. Assign a *reserved* public IP (free while
   attached) so the DNS record stays stable. Note: Ampere A1 capacity is
   contended and free tenancies often get *"Out of capacity"* for days.
   Upgrading to **Pay As You Go** (temporary ~$100 card hold, no charge) gives
   capacity priority while all Always Free resources stay free; keep resources
   within the Always Free limits and add a $1 budget alert as a guardrail.
2. **Install Docker** on the VM, then clone the repo.
3. **Env**: `cp .env.production.example .env` and fill it in. Set
   `POSTGRES_PASSWORD`, the API keys, `NOSTOS_API_TOKEN` (the endpoint is
   public!), and `NOSTOS_ALLOWED_ORIGINS` (JSON list with your app origin and
   the gh-pages origin).
4. **Deploy**: `./scripts/deploy.sh` — builds the images, starts Postgres +
   Redis, applies `schema.sql` (idempotent), then starts `web` + `worker`.
   Containers restart automatically (`restart: unless-stopped`).
5. **HTTPS**: point `xen-ia.nostos.dev` at the VM IP with a Cloudflare proxy
   (orange cloud) A record — Cloudflare terminates TLS and talks plain HTTP to
   the origin on port 80, so no certificate management. `/healthz` (liveness)
   and `/readyz` (readiness) are exposed.
6. **Resend**: add `xen-ia.nostos.dev` as the sending domain in Resend and add
   its TXT/SPF/DKIM records in Cloudflare DNS (the app host doubles as the
   sending domain, so no extra subdomain to manage; Resend is send-only, so no
   MX record is required). Set
   `NOSTOS_EMAIL_FROM_ADDRESS="Nostos <hello@xen-ia.nostos.dev>"`.
7. **Keep-alive**: Always Free VMs are reclaimed when idle (7 days below ~20%
   CPU/network/memory). A cron hitting `/healthz` every minute avoids this:

   ```
   * * * * * curl -fsS https://xen-ia.nostos.dev/healthz >/dev/null 2>&1 || true
   ```

Updating is `git pull && ./scripts/deploy.sh`. The stack is the same image the
Railway path uses, so switching platforms later is just a matter of the host.