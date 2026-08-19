# TODO — next steps

Reference branches:

- `deploy/oracle-free-tier` — self-hosted deploy artifacts (already on top of `dev`)
- `perf/llm-tool-usage` — LLM/flight search tool usage rework (WIP: only a TODO comment)
- `feature/wire-rag-knowledge` — wire the knowledge base into the pipeline (WIP: only a TODO comment)

## Working model

- Development branches always branch off `dev` (never off `main`).
- Each branch → PR into `dev`, then:
  ```bash
  git switch main
  git merge --no-ff dev
  git push
  ```
- Tests: `uv run pytest` (currently 56 passed, 1 skipped).

---

## 1. Go live on Oracle Free Tier — branch `deploy/oracle-free-tier`

Deploy artifacts already in the repo: `docker-compose.prod.yml`, `.env.production.example`,
`scripts/deploy.sh`, README section *Deploy (self-hosted VM — Oracle Cloud Free Tier)*.
Domain decision taken: apex **`xen-ia.org`**, backend + sending domain **`nostos.xen-ia.org`**,
email from **`hello@nostos.xen-ia.org`**.

- [x] **Buy `xen-ia.org`** on Cloudflare Registrar ($8.50/yr, wholesale). DNS managed by Cloudflare.
- [x] **Oracle account** (`signup.cloud.oracle.com`, card only for identity verification, no charge).
  Region **`eu-milan-1`** (fallback: `eu-frankfurt-1` if "out of capacity"). Upgraded to **PAYG**
  (temporary ~$100 card hold, no charge) to get capacity priority for the Ampere A1 instance;
  keep all resources within Always Free limits + a $1 budget alert as a guardrail.
- [x] **Create VM** — Ampere A1, **2 OCPU / 12 GB** (the current Always Free limit since 2026-06),
  Ubuntu 24.04 ARM, default boot volume. Attach a **reserved public IP** (free while attached).
  VCN Security List: open only **22** (SSH) and **80** (HTTP for the Cloudflare proxy).
  Done: VM running, public IP assigned, VCN + public subnet, Internet Gateway + route,
  security list 22+80.
- [x] **Install Docker** + compose plugin on the VM; clone the repo. Done: Docker 29.1.3,
  Compose 2.40.3, git 2.43.0 installed on the VM.
- [x] **Env**: `cp .env.production.example .env` and fill: `POSTGRES_PASSWORD`, `NOSTOS_API_TOKEN`
  (long random), LLM key, `NOSTOS_SERPAPI_KEY`, `NOSTOS_RESEND_API_KEY`, `NOSTOS_WHITELIST_EMAILS`.
  Done on the VM: `.env` compiled with all keys.
- [x] **Deploy**: `./scripts/deploy.sh` (build → start postgres/redis → apply idempotent
  `schema.sql` → sync whitelist → start web/worker). All services `restart: unless-stopped`.
  Done: 6/6 containers up (postgres/redis healthy, web on port 80), `/healthz` ok,
  `/readyz` ready.
- [x] **Reserved public IP**: attach one to the VM in OCI so the DNS record stays stable
  across reboots (the VM currently runs on an ephemeral public IP). Done: existing IP
  reserved via VNIC → "Reserve IPv4 address" (same address kept).
- [x] **DNS**: A record `nostos.xen-ia.org` → VM IP, **Cloudflare proxy ON** (orange cloud →
  free HTTPS, origin hidden, Cloudflare→origin on port 80). Verify `https://nostos.xen-ia.org/healthz`.
  Done: record proxied, SSL/TLS mode **Flexible** (origin listens on HTTP:80), healthz ok.
- [x] **Resend**: add `nostos.xen-ia.org` as sending domain, add its TXT/SPF/DKIM records in
  Cloudflare DNS. Done: domain **Verified** (DKIM `resend._domainkey.nostos`, SPF + MX on
  `send.nostos`), email received from `hello@nostos.xen-ia.org`.
- [x] **Keep-alive**: add the anti-idle cron hitting `/healthz` every minute (Oracle reclaims
  Always Free VMs idle for 7 days below ~20% CPU/network/memory). Done: cron active, verified
  via web logs.
- [x] **Frontend**: gh-pages API base → `https://nostos.xen-ia.org/api/v1`
  (CORS origin `https://nostos.xen-ia.org` already in `.env.production.example`). Done in code;
  gh-pages will be republished on the next push to `dev`.
- [x] **Decommission the quick tunnel** + stop depending on the Mac being on. Done: `pkill -f
  cloudflared` on the Mac (tunnel only pointed at local port 3072).
- [x] **Final verification**: `/healthz`, `/readyz`, a real trip (PENDING→RUNNING→DONE), email
  received from the real sending domain (`hello@nostos.xen-ia.org`). Done end-to-end.
- [x] **SSH hardening**: disable password auth on the VM (`PasswordAuthentication no`). (Optional
  but recommended; skip if the key setup isn't confirmed yet.)

Note: with `POSTGRES_PASSWORD` in `.env` the compose stack overrides the internal URLs
(`redis:6379` / `postgres:5432`) — no local Redis/Postgres needed on the VM.

---

## 1b. Serve the frontend from the app origin (post-go-live)

`nostos.xen-ia.org` is only the API backend today; the mock frontend lives on gh-pages
(`xen-ia.github.io`) and needs a CORS whitelist entry. Better: serve `docs/index.html` from the
same origin as the API → same-origin requests, no CORS at all, single deployable unit on the VM,
and the apex `xen-ia.org` stays free for a future landing page.

- [ ] Mount `docs/index.html` as static files at `/` in the web container (FastAPI `StaticFiles`),
      API keeps `/api/v1`; no conflict with `/healthz`/`/readyz`.
- [ ] Frontend then calls the same origin (no `API_BASE` override needed; drop the localStorage
      fallback or default it to the same origin).
- [ ] Drop `https://xen-ia.github.io` from `NOSTOS_ALLOWED_ORIGINS` (keep `https://nostos.xen-ia.org`
      or relax CORS entirely since it becomes same-origin).
- [ ] Deploy: frontend changes ship with the app image (no separate gh-pages step).
- [ ] Decide later: serve a real landing page at the apex `xen-ia.org`.

---

## 1c. Email whitelist gate (current feature)

`POST /trips` is gated so only invited emails can create trips; this protects the paid LLM
budget from anyone hitting the public endpoint. Design (agreed with owner):

- Table `email_whitelist(email PRIMARY KEY, created_at)` in `schema.sql`.
- Registry is env `NOSTOS_WHITELIST_EMAILS` (JSON list) — lives in `.env` on the VM, NOT in git.
  `scripts/deploy.sh` syncs env → table on every deploy (**add-only**, idempotent `INSERT ...
  ON CONFLICT DO NOTHING`). Manual `INSERT`s via psql/DBeaver are welcome and **never wiped**;
  removals are manual (`DELETE FROM email_whitelist WHERE email = '...'`).
- Gate is **always on, deny-all**: no toggle. Check happens in `create_trip`
  (`src/api/routers/trips.py`) right after auth → `403 not_whitelisted`
  (`https://xen-ia.org/problems/not_whitelisted`). Empty list = nobody can create.
- Per-email **daily cap** `NOSTOS_WHITELIST_DAILY_MAX` (default 5) POSTs/day, reusing the Redis
  `RateLimiter` (key `email:{email}:{YYYY-MM-DD}`) → `429 rate_limited`.
- Only `POST /trips` is gated; status + feedback endpoints stay token-gated only.

- [x] Tests (TDD, RED→GREEN): deny unlisted / allow listed / deny-all on empty / daily cap per
      email / daily cap is per-email. 56 passed, 1 skipped.
- [x] Implementation: gate + daily cap in router, `Database.is_whitelisted`, table in schema,
      sync step in `scripts/deploy.sh`, settings `whitelist_daily_max`.
- [x] Side change: `trip_history` now records which `model` produced the trip (column `model`,
      passed worker → orchestrator → `save_trip_history`) and `created_at` renamed to `timestamp`.
- [ ] Set `NOSTOS_WHITELIST_EMAILS` on the VM `.env` (owner email) + `./scripts/deploy.sh`.
- [ ] **Tool I/O logging (deferred)** — see `perf/llm-tool-usage`: persist **every** SerpAPI tool call
      made for a trip — inputs (query params per flights/maps/places) AND raw outputs — not just the
      final `package_json`.

Note: `POST /trips/{trip_id}/feedback` is deliberately **not** gated (user feedback is not
structured/spam-worthy); revisit if abuse shows up.

---

## 2. LLM tool usage rework — branch `perf/llm-tool-usage`

Current state: branch has only a TODO in `src/tools/flights.py`:

> "Implementare ricerca libera: non 5 ricerche uguali, ma sondare più ricerche da più angoli;
> cercare voli da più partenze e scegliere il più economico"

Also deferred here: full tool I/O logging. `trip_history.package_json` already stores the final
package; the owner wants **every** SerpAPI tool call persisted — inputs (flights/maps/places query
params) and raw outputs — not just the final package. Cut from the whitelist feature: add a
`package_json`-style column (e.g. `tool_log_jsonb`) populated by the orchestrator at each search
call site in `_compose_package`.

Today `TripOrchestrator._compose_package` (`src/core/orchestrator.py:157`) fires one
`flights.search(departure_code, destination_code, start, end, …)` — a single query, 5 near-identical
results. The intent (`TripIntent`) fixes one departure airport.

- [ ] Decide the search strategy: probe multiple angles (alternative nearby departure airports,
      flexible date windows when `flexible_dates`, direct vs 1-stop) and pick the cheapest/best.
- [ ] Extend `TripIntent` (`src/core/models.py`) + `build_intent_prompt` if the model should
      express alternative departures / date flexibility; keep pydantic tool-schema validation and
      Ollama grammar compatibility (`make_ollama_schema` in `src/services/tools/__init__.py`).
- [ ] Rework `flights.search` (`src/services/tools/flights.py`) to fan out and rank, bounded by
      the SerpAPI timeout; keep the `_normalize` output shape and logging.
- [ ] Keep the LLM extraction constrained (`tool_choice` forced, single `extract` tool in
      `src/services/apis/llm.py`) unless a multi-turn tool loop is explicitly part of the design.
- [ ] Tests: update `tests/test_orchestrator.py` mocks + add flights fan-out unit tests.

---

## 3. Wire the knowledge base (RAG) — branch `feature/wire-rag-knowledge`

Reference: `docs/adr/006-knowledge-service.md` (Accepted). Current state: `src/knowledge.py` empty
except a TODO; 8 markdown reports under `src/knowledge/` (camerun, creta ×2, croazia ×2, indonesia,
islanda, sicilia); `NOSTOS_QDRANT_URL` setting exists but unused.

The KB files have YAML frontmatter (`destinazioni`, `periodo`, `stagione`, `tipo_viaggio`,
`viaggio_precedente_correlato`, `autore`) and per-stop `###` blocks (Identità e atmosfera, Come
l'abbiamo trovata, Cosa abbiamo fatto, Da evitare, Sostenibilità, Logistica) — designed so each
block is retrievable standalone.

### 3a. Decision — KB structure & retrieval strategy (blocking)

- [ ] **Option A — vector DB (Qdrant)**: index blocks with embeddings, semantic retrieval on
      `NOSTOS_QDRANT_URL`. Adds an infra dependency + embedding step; best fuzzy matching.
- [ ] **Option B — llm-wiki-like**: keep markdown as source of truth, retrieve by frontmatter
      match (destination/season/type) + keyword on section blocks, no extra infra. Simpler, no
      new service, degrades gracefully on unknown destinations.
- [ ] Record the choice (extend ADR-006 or add a retrieval-strategy ADR).

### 3b. Implementation

- [ ] Implement `src/services/knowledge/` as a service behind an interface, with a fake for tests
      (per ADR-006). Move `src/knowledge/*.md` under `src/services/knowledge/`.
- [ ] Hook it into `TripOrchestrator` between intent extraction and research: after
      `_extract_intent` (`src/core/orchestrator.py:80`), retrieve knowledge for the destination
      and pass the structured, actionable info (off-season tips, authentic spots, avoid-list)
      as extra input to the SerpAPI searches in `_compose_package`.
- [ ] Decide (deferred in ADR-006) whether the retrieved knowledge also feeds email composition.
- [ ] Tests: fake knowledge service + orchestrator integration.

---

## Cross-cutting

- [ ] Keep `AGENTS.md` conventions: `uv run`, venv outside the workspace, English code/docs.
- [ ] Every PR green on `uv run pytest` before merging into `dev`.
