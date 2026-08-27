# TODO — Comprehensive Issue Tracking

Reference branches:
- `deploy/oracle-free-tier` — self-hosted deploy artifacts (already on top of `dev`)
- `perf/llm-tool-usage` — LLM/flight search tool usage rework (WIP: only a TODO comment)
- `feature/wire-rag-knowledge` — wire the knowledge base into the pipeline (WIP: only a TODO comment)
- `feat/travel-mode-pipeline` — travel mode pipeline with intent fields, targeted searches, mode-aware email
- `fix/frontend-and-email` — frontend feedback fix + email composer improvements (merged)

## Working model
- Development branches always branch off `dev` (never off `main`).
- Each branch → PR into `dev`, then merge `dev` → `main` via fast-forward or squash.
- Tests: `uv run pytest` (currently **116 passed, 1 skipped**).

---

## Architecture Health Score (Current State)

```
Architecture Health Score
=========================

Coupling              █████░░░░░  [Needs Work] - Some cross-layer coupling (orchestrator→tools→SerpAPI)
Cohesion              ██████░░░░  [Good] - Components have clear single responsibilities
Abstraction Level     ██████░░░░  [Good] - Clean layers (API → orchestrator → tools → APIs)
Testability           ███████░░░  [Good] - 116 tests, fakes for Redis/LLM/DB, integration tests
Pattern Consistency   ██████░░░░  [Good] - ADR-driven, consistent DI, clear boundaries

Overall: Solid foundation with clear layering; 2-3 high-impact fixes needed for production polish
```

---

## Findings Table — All Open Issues

| ID | Severity | Finding | Impact | Fix | Effort | Unlocks |
|----|----------|---------|--------|-----|--------|---------|
| F1 | **CRITICAL** | `departure_codes` = 0 for "Italia" → no flights searched | No flight options in email for domestic/international trips; user sees only stays/POIs | Fix `build_geo_prompt` + `DepartureAirports` extraction to infer airport codes from country/region; validate in `geo_plan` | Medium (4-6h) | Flight search works for all destinations |
| F2 | **HIGH** | Maps queries use `hl=it` for non-Latin destinations (China) → poor results | Chinese destinations return Italian-language results, low relevance | Detect destination script/locale → auto-set `hl`/`gl` (e.g., `hl=zh-CN`/`gl=cn` for China) | Medium (3-4h) | Relevant POIs for all destinations |
| F3 | **HIGH** | 48 link-less Maps results dropped (wasted SerpAPI quota) | ~50% of Maps calls return link-less results → wasted API calls | Add `"site:google.com/maps"` or `"place_id"` filter to queries; tighten query specificity | Low (1-2h) | Reduced SerpAPI costs, better results |
| F4 | **HIGH** | `departure_location` "Italia" not resolved to airport codes | User enters country/region but no flights searched | Enhance `TripIntent` extraction + `geo_plan` to infer major airports from country/region (e.g., Italy → MXP/FCO/VCE/BLQ) | Medium (3-4h) | Flights work for generic locations |
| F5 | **MEDIUM** | No departure city/city inference from IP/whitelist | User must manually specify departure; friction | Add optional IP-based geo inference or default from whitelist email domain | Low (1-2h) | Better UX, fewer required fields |
| F6 | **MEDIUM** | Tool I/O logging incomplete — only final `package_json` stored | Debugging failed trips hard; no visibility into SerpAPI raw I/O | Add `tool_log_jsonb` column; persist every SerpAPI call (inputs + raw outputs) in `_compose_package` | Medium (3-4h) | Full observability, faster debugging |
| F7 | **MEDIUM** | Flight search fan-out not implemented (single query per departure) | Suboptimal flight prices; no exploration of nearby airports/date shifts | Implement fan-out: nearby airports ±3 days when `flexible_dates`, rank by price/duration | Significant (1-2 days) | Better flight prices, user trust |
| F8 | **MEDIUM** | Knowledge base (RAG) not wired (`feature/wire-rag-knowledge`) | No local knowledge injection; generic recommendations | Implement `src/services/knowledge/` (Option B: frontmatter match) + hook into orchestrator | Significant (1-2 days) | Authentic local tips, differentiated product |
| F9 | **MEDIUM** | Frontend served from gh-pages (cross-origin) instead of same origin | CORS complexity, extra deploy step, `API_BASE` hardcoded | Mount `docs/index.html` as FastAPI `StaticFiles` at `/`; API at `/api/v1`; drop gh-pages | Medium (2-3h) | Single deploy, no CORS, simpler ops |
| F10 | **LOW** | `TripStore` Redis TTL = 24h → status lost after 24h even if email sent | `GET /trips/{id}` returns 404 after 24h despite email sent | Make Postgres the source of truth for status (add `status` column to `trip_history` already done); Redis as cache only | Low (1-2h) | Reliable status after 24h |
| F11 | **LOW** | No landing page at apex `xen-ia.org` | Brand presence missing | Create static landing page at `/` (separate from app) or serve marketing page | Low (1-2h) | Professional brand presence |
| F12 | **LOW** | No metrics/observability (Prometheus, tracing) | Can't measure latency, error rates, LLM costs | Add Prometheus metrics (request latency, LLM token counts, SerpAPI calls) + structured logging | Medium (3-4h) | Production observability |
| F13 | **LOW** | No automated E2E tests (Playwright/Cypress) | Manual regression testing only | Add 4-scenario E2E suite (fixed, road_trip, van_life, sailing) in CI | Medium (2-3h) | Regression confidence |
| F14 | **LOW** | `NOSTOS_ALLOWED_ORIGINS` still includes gh-pages after same-origin move | Dead config | Remove gh-pages from allowed origins once same-origin deployed | Trivial | Clean config |

---

## Completed Recently (Last 2 Weeks)

| ID | Title | Branch | Status |
|----|-------|--------|--------|
| ✅ | Travel mode pipeline — `travel_mode`, `accommodation_style`, `mobility_preferences` in `TripIntent` | `feat/travel-mode-pipeline` | Done |
| ✅ | All 6 LLM prompts updated to use new fields | `feat/travel-mode-pipeline` | Done |
| ✅ | Maps queries enriched with travel_mode/mobility qualifiers | `feat/travel-mode-pipeline` | Done |
| ✅ | Places query built from travel_mode/accommodation_style | `feat/travel-mode-pipeline` | Done |
| ✅ | Curation prompt prioritizes flights for fixed/intercontinental | `feat/travel-mode-pipeline` | Done |
| ✅ | Email template renders mode/mobility sections | `feat/travel-mode-pipeline` | Done |
| ✅ | `package_json` → `trip_dossier` + COMMENT ON COLUMN for all 20 cols | `feat/travel-mode-pipeline` | Done |
| ✅ | Public feedback endpoint `POST /feedback/public` (IP rate-limited) | `fix/frontend-and-email` | Done |
| ✅ | Frontend feedback URL fixed to `/feedback/public` | `fix/frontend-and-email` | Done |
| ✅ | Public trip status endpoint `GET /status/public` (Redis + Postgres fallback) | `fix/frontend-and-email` | Done |
| ✅ | Frontend polling fixed to use `/status/public` | `fix/frontend-and-email` | Done |
| ✅ | `package_json` renamed to `trip_dossier` with COMMENT ON COLUMN | `feat/travel-mode-pipeline` | Done |
| ✅ | Auto-deploy workflow (GitHub Actions → VM via SSH) | `.github/workflows/deploy.yml` | Done |
| ✅ | `NOSTOS_WHITELIST_DAILY_MAX` env var for daily cap | settings | Done |
| ✅ | 116 tests passing | — | Done |

---

## Next Priority Order (Recommended)

1. **F1 + F4** — Fix departure codes (enables flights for all trips)
2. **F2** — Fix Maps locale for non-Latin destinations
3. **F3** — Reduce link-less Maps waste
4. **F6** — Full tool I/O logging (debugging velocity)
5. **F7** — Flight fan-out (better prices)
6. **F8** — Knowledge base wiring (product differentiation)
6. **F9** — Same-origin frontend (ops simplification)
7. **F5, F10, F12, F13** — UX polish, observability, reliability

---

## Architecture Decision Records (ADRs) — Status

| ADR | Title | Status | Notes |
|-----|-------|--------|-------|
| ADR-001 | Queue (ARQ) | Accepted | Redis + ARQ worker |
| ADR-002 | Source of truth (Postgres) | Accepted | Redis cache, PG durable |
| ADR-003 | Lease (claim/renew/release) | Accepted | 60s heartbeat |
| ADR-004 | API contract | Accepted | 202 + Location header |
| ADR-005 | Outbox-lite | Accepted | status column + upsert |
| ADR-006 | Knowledge service | Accepted | Qdrant URL exists, unused |
| ADR-007 | Flexible dates dropped | Accepted | Re-added in ADR-009 |
| ADR-008 | Co-design form pipeline | Accepted | Form v2 + pipeline |
| ADR-009 | Flexible dates real semantics | Accepted | Hard vs indicative |
| ADR-010 | Travelers composition removal | Accepted | Replaced by travelers_type |

---

## Cross-cutting Concerns

- [ ] Keep `AGENTS.md` conventions: `uv run`, venv outside workspace, English code/docs
- [ ] Every PR green on `uv run pytest` before merging into `dev`
- [ ] Update `PRODUCT.md` (currently stale — describes old budget chips, interests chips)
- [ ] Decision on ADR-006 knowledge retrieval strategy (Option A: Qdrant vs Option B: frontmatter match)

---

## Test Coverage Summary

| Test Suite | Tests | Status |
|------------|-------|--------|
| `test_api.py` | 24 | ✅ |
| `test_contract.py` | 4 | ✅ |
| `test_database_sql.py` | 4 | ✅ |
| `test_email_rendering.py` | 4 | ✅ |
| `test_flight_matrix.py` | 8 | ✅ |
| `test_geo_models.py` | 12 | ✅ |
| `test_integration_worker.py` | 6 | ✅ |
| `test_orchestrator.py` | 12 | ✅ |
| `test_pure.py` | 8 | ✅ |
| `test_schemas.py` | 4 | ✅ |
| `test_services.py` | 4 | ✅ |
| `test_database.py` | 20 | ✅ |
| `test_fakes.py` | 4 | ✅ |
| `test_tools.py` | 4 | ✅ |
| `test_worker.py` | 4 | ✅ |
| **Total** | **116 passed, 1 skipped** | ✅ |

---

## Deploy Checklist (for next `dev` → `main` merge)

- [ ] Run full test suite: `uv run pytest`
- [ ] Update `PRODUCT.md` if schema/fields changed
- [ ] Merge `dev` → `main` (triggers auto-deploy workflow)
- [ ] Verify VM deploy: `./scripts/deploy.sh` completes, all 6 containers up
- [ ] Health checks: `/healthz`, `/readyz` → 200
- [ ] Smoke test: POST `/api/v1/trips` → 202, polling → DONE, email received
- [ ] Feedback test: POST `/feedback/public` → 201
- [ ] If gh-pages still used: `cd docs && git push origin HEAD:gh-pages -f`
- [ ] Update `PRODUCT.md` with current field descriptions

---

*Last updated: 2026-08-27 — after successful end-to-end test (China trip, 25.5s total, email sent, feedback 201)*