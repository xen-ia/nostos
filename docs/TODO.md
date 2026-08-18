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
- Tests: `uv run pytest` (currently 50 passed, 1 skipped).

---

## 1. Go live on Oracle Free Tier — branch `deploy/oracle-free-tier`

Deploy artifacts already in the repo: `docker-compose.prod.yml`, `.env.production.example`,
`scripts/deploy.sh`, README section *Deploy (self-hosted VM — Oracle Cloud Free Tier)*.
Domain decision taken: apex **`nostos.dev`**, backend + sending domain **`xen-ia.nostos.dev`**,
email from **`hello@xen-ia.nostos.dev`**.

- [ ] **Buy `nostos.dev`** on Cloudflare Registrar (~$20/yr, wholesale). DNS managed by Cloudflare.
- [x] **Oracle account** (`signup.cloud.oracle.com`, card only for identity verification, no charge).
  Region **`eu-milan-1`** (fallback: `eu-frankfurt-1` if "out of capacity"). Upgraded to **PAYG**
  (temporary ~$100 card hold, no charge) to get capacity priority for the Ampere A1 instance;
  keep all resources within Always Free limits + a $1 budget alert as a guardrail.
- [x] **Create VM** — Ampere A1, **2 OCPU / 12 GB** (the current Always Free limit since 2026-06),
  Ubuntu 24.04 ARM, default boot volume. Attach a **reserved public IP** (free while attached).
  VCN Security List: open only **22** (SSH) and **80** (HTTP for the Cloudflare proxy).
  Done: VM running, public IP assigned, VCN + public subnet, Internet Gateway + route,
  security list 22+80. TODO: attach a *reserved* public IP.
- [x] **Install Docker** + compose plugin on the VM; clone the repo. Done: Docker 29.1.3,
  Compose 2.40.3, git 2.43.0 installed on the VM.
- [x] **Env**: `cp .env.production.example .env` and fill: `POSTGRES_PASSWORD`, `NOSTOS_API_TOKEN`
  (long random), LLM key, `NOSTOS_SERPAPI_KEY`, `NOSTOS_RESEND_API_KEY`. Done on the VM:
  `.env` compiled with all keys.
- [ ] **Deploy**: `./scripts/deploy.sh` (build → start postgres/redis → apply idempotent
  `schema.sql` → start web/worker). All services `restart: unless-stopped`.
- [ ] **DNS**: A record `xen-ia.nostos.dev` → VM IP, **Cloudflare proxy ON** (orange cloud →
  free HTTPS, origin hidden, Cloudflare→origin on port 80). Verify `https://xen-ia.nostos.dev/healthz`.
- [ ] **Resend**: add `xen-ia.nostos.dev` as sending domain, add its TXT/SPF/DKIM records in
  Cloudflare DNS (no MX needed — send-only). `NOSTOS_EMAIL_FROM_ADDRESS` already set.
- [ ] **Keep-alive**: add the anti-idle cron hitting `/healthz` every minute (Oracle reclaims
  Always Free VMs idle for 7 days below ~20% CPU/network/memory).
- [ ] **Frontend**: gh-pages API base → `https://xen-ia.nostos.dev/api/v1`
  (CORS origin `https://xen-ia.nostos.dev` already in `.env.production.example`).
- [ ] **Decommission the quick tunnel** + stop depending on the Mac being on.
- [ ] **Final verification**: `/healthz`, `/readyz`, a real trip (PENDING→RUNNING→DONE), email
  received on a non-owner address.

Note: with `POSTGRES_PASSWORD` in `.env` the compose stack overrides the internal URLs
(`redis:6379` / `postgres:5432`) — no local Redis/Postgres needed on the VM.

---

## 2. LLM tool usage rework — branch `perf/llm-tool-usage`

Current state: branch has only a TODO in `src/tools/flights.py`:

> "Implementare ricerca libera: non 5 ricerche uguali, ma sondare più ricerche da più angoli;
> cercare voli da più partenze e scegliere il più economico"

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
