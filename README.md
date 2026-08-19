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

Nostos is a small, layered pipeline: the web layer accepts and validates, the
core orchestrates, the services reach the outside world, and the
infrastructure layer persists and queues. The interesting part — the part that
makes or breaks the product — is the dialogue between the LLM and the trip
request: everything else is plumbing that exists to serve it.

```text
                   ┌─────────────────────────────────────────────────┐
  browser ──POST──►│  api  (FastAPI)                                 │
                   │  • validate + whitelist gate                    │
                   │  • enqueue (ARQ)                                │
                   └──────────────┬──────────────────────────────────┘
                                  │ job
                                  ▼
                   ┌─────────────────────────────────────────────────┐
                   │  worker (separate process)                      │
                   │  orchestrator:                                  │
                   │    LLM intent → SerpAPI → LLM email → Resend    │
                   └──────┬───────────────────────┬──────────────────┘
                          │                       │
                          ▼                       ▼
                   ┌──────────────┐       ┌──────────────────┐
                   │  Redis       │       │  Postgres        │
                   │  trip state  │       │  trip_history    │
                   │  + lease     │       │  + feedback      │
                   └──────────────┘       └──────────────────┘
```

Follow a trip and you will meet every layer:

1. **The browser submits** the form (`docs/index.html`). The payload is
   deliberately simple — email, destination, dates, a few selects — and a
   `free_text` field leaves room for the signals that matter most: "not the
   usual places", "away from the crowds". Those signals are precious data and
   the system is built around treating them as such.

2. **FastAPI accepts** (`src/api/routers/trips.py`). Every request is checked
   against the email whitelist (the endpoint is public, so the whitelist is
   the gate) and rate-limited. The API never does the work: it creates a trip
   record in Redis, enqueues an ARQ job, and answers `202 Accepted` with a
   `Location` header.

3. **The worker picks it up** (`src/infrastructure/worker.py`). A separate
   process (it must run for trips to actually execute) claims the trip with an
   atomic Redis lock, so a trip can never run twice. This is where the
   pipeline runs:

   - **Intent** — the LLM reads the request (`TripIntent` schema) and turns it
     into structured fields: destination, airport codes, interests, style,
     pace, constraints. Structured inputs from the form — travelers
     composition, budget, travel mode, stay preference — join the free text
     here, so the model composes against real constraints.
   - **Research** — SerpAPI searches flights, points of interest and
     accommodations (`src/services/tools/`). A category with no valid results
     is dropped; if everything comes back empty, the trip stops and no email
     is sent.
   - **Composition** — a second LLM call writes the email (`EmailContent`
     schema) against a strict editorial voice (`src/core/prompts/system_prompt.md`),
     using *only* the researched resources — nothing invented.
   - **Delivery** — Resend sends the email. The history is persisted in
     Postgres with status, the model used, and the app version.

4. **The infrastructure remembers** (`src/infrastructure/`). Redis holds the
   trip's live state and its lease; Postgres (`schema.sql`) keeps the durable
   history — inputs, the researched package, subject/body, status, model,
   version, and timing — so you can audit every trip long after the Redis
   record has expired. A `feedback` table closes the loop on quality.

The layers are easy to read in the file tree: `src/api/` (web), `src/core/`
(orchestration + LLM schemas), `src/services/` (LLM/SerpAPI/Resend clients and
search tools), `src/infrastructure/` (storage, queue, worker). Every design
decision behind this shape is recorded in `docs/adr/`.

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
5. **HTTPS**: point `nostos.xen-ia.org` at the VM IP with a Cloudflare proxy
   (orange cloud) A record — Cloudflare terminates TLS and talks plain HTTP to
   the origin on port 80, so no certificate management. `/healthz` (liveness)
   and `/readyz` (readiness) are exposed.
6. **Resend**: add `nostos.xen-ia.org` as the sending domain in Resend and add
   its TXT/SPF/DKIM records in Cloudflare DNS (the app host doubles as the
   sending domain, so no extra subdomain to manage; Resend is send-only, so no
   MX record is required). Set
   `NOSTOS_EMAIL_FROM_ADDRESS="Nostos <hello@nostos.xen-ia.org>"`.
7. **Keep-alive**: Always Free VMs are reclaimed when idle (7 days below ~20%
   CPU/network/memory). A cron hitting `/healthz` every minute avoids this:

   ```
   * * * * * curl -fsS https://nostos.xen-ia.org/healthz >/dev/null 2>&1 || true
   ```

Updating is `git pull && ./scripts/deploy.sh`.