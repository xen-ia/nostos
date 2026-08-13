# Architecture Review — nostos (kees97/claude-architecture-skills)

Review of the nostos system design and software architecture, conducted with the
`software-architecture` skill. The goal is an honest, trade-off-driven audit of
what is already well placed and what blocks production, with concrete fixes that
reference `file:line`.

**Audit date**: 2026-08-13 — **Scope**: `main.py`, `src/` (pipeline, routers,
apis, tools, prompts, models, trip_store, database, settings, dependencies),
`schema.sql`, `docs/index.html`, `pyproject.toml`.

---

## Architecture Health Score

```
Architecture Health Score
=========================

Coupling              ██████░░░░  [Good] - clean inward layering, no circular imports; leaks: tools depend on a global settings singleton, EmailSender mutates a module-level SDK key
Cohesion             █████░░░░░  [Good] - each module has one purpose; TripOrchestrator mixes orchestration + text rendering + copy constants
Abstraction Level    ██████░░░░  [Good] - LLM provider Protocol is right-sized; tools/data/email are concrete where an interface costs nothing but buys testability
Testability          ██░░░░░░░░  [Critical Issues] - zero tests; no seam to inject fake LLM/SerpAPI/email; module-level functions + import-time state
Pattern Consistency  █████░░░░░  [Needs Work] - Provider/Protocol used for LLM but not for search tools or persistence; wrong return annotation in _compose_package
```

**Overall**: A well-layered, honestly-scoped monolith that is architecturally
correct for a working prototype but not production-ready: the workflow executes
in-process with no durable substrate, email→history is a fragile dual-write, the
source of truth is split between Redis (TTL 24h) and Postgres, and there is no
seam for testing any of it. The refactor needed is **evolutionary, not a
rewrite** — the good bones are already there.

---

## 1. Context & Requirements Restatement

Before judging, the real shape of the system:

- **What it does**: `POST /trips` accepts a trip request → LLM extracts intent →
  SerpAPI searches flights/POIs/stays → LLM composes an email → Resend sends it →
  Postgres stores history. The HTTP call returns immediately; the flow runs in the
  background.
- **Scale targets**: effectively a demo/small pilot. Single instance, single
  process, handful of users, minutes-long workflows, real money spent per run
  (LLM tokens + SerpAPI credits).
- **Operational constraints**: no SLA, no CI, no containerization, manual
  `schema.sql` apply. Runs on a single host.
- **Coupling points**: the request path and the workflow path are fused in one
  process (`background_tasks.add_task`). That is the single most load-bearing
  decision in the system and the root of most findings.
- **Common change patterns**: adding a new search capability (tool), adding a new
  LLM provider, changing email copy/template, adding feedback endpoints. These
  should each be a one-file change.

---

## 2. Findings Table

| ID | Severity | Finding | Impact | Fix | Effort | Unlocks |
|----|---------|---------|--------|-----|--------|---------|
| F1 | CRITICAL | Workflow runs in-process via `background_tasks.add_task` (`src/routers/trips.py:35`) | A crash, deploy, or restart loses in-flight trips forever (stuck `PENDING`/`RUNNING`); no redelivery, no horizontal scale | Move to a durable queue (Redis Stream/ARQ) + dedicated worker process; reuse existing `SET NX EX` claim as lease | Significant (1-2 days) | F2, F5, horizontal scale |
| F2 | CRITICAL | Dual-write email/history without transactional outbox (`src/pipeline.py:75-78`) | If the Postgres insert fails after the email is sent, the email exists with no record (and vice-versa on retry); billing/audit/tracking break silently | Persist `trip+intent+package+email_content` in Postgres before any external I/O; a dispatcher drains the outbox to Resend; `status=sent` only on confirmation | Significant (1-2 days) | Production accounting, retries |
| F3 | HIGH | Ambiguous source of truth: trip state in Redis with TTL 24h vs. durable history in Postgres (`src/trip_store.py:70`, `src/database.py`) | After 24h `GET /trips/{id}` returns 404 even though the email was sent and stored — UX and operations contradict the data | Make Postgres the system of record (add `status` to `trip_history` or a `trips` table); Redis becomes a short-TTL cache or is dropped in favor of the job queue | Moderate (half day) | F1, F5 |
| F4 | HIGH | No test seams anywhere: SDK clients constructed inside constructors, module-level functions, global settings singleton | Business logic (pipeline, stores) cannot be tested without network/Redis/Postgres; the most expensive part of the system is the least verified | Inject fakes: `AnthropicClient`/`OpenAIClient`/`OllamaClient` accept a client factory; SerpAPI `search()` takes an injected client + key; Database takes an interface | Moderate (half day) | Test suite (F5), safe refactors |
| F5 | HIGH | No tests, no CI, no lint/typecheck gates (`pyproject.toml`) | Every refactor above is a leap of faith; regressions in the money path ship silently | Add pytest + a thin seam layer, CI job per PR | Moderate (half day for infra) | All other fixes land safely |
| F6 | MEDIUM | Orchestrator is a monolithic sequential `run()` with private `_*` helpers; no retry/redelivery granularity (`src/pipeline.py:60-83`) | Any stage failure aborts the whole trip; no partial recovery; a transient SerpAPI timeout wastes the trip | Split into explicit stages (intent → gather → compose → send → persist) with per-stage retry and idempotent re-entry | Moderate (half day) | F1 |
| F7 | MEDIUM | Lock lease (300s) shorter than worst-case workflow duration (`src/pipeline.py:32`, `src/main.py:35-45`) | With `--serpapi-timeout 180` × 3 parallel searches + LLM + email, a run can exceed the 300s lease; a second worker would re-run the trip (double email, double cost) | Make lease renewable or TTL-bounded to the stage, or compute lease as a function of configured timeouts | Quick (< 1 hour) | F1 |
| F8 | MEDIUM | Wrong return annotation: `_compose_package` annotated `-> tuple[dict, dict]` returns a 4-tuple (`src/pipeline.py:139,192`) | Type lie hides the real contract; tooling/mypy would mislead; a reader can't tell what the method returns | Annotate `-> tuple[dict, str, str, dict]` or return a small dataclass | Quick (< 1 hour) | — |
| F9 | MEDIUM | Tools swallow errors and return `[]`; SerpAPI client built per-call from a global `get_settings()` (`src/tools/*.py`, `src/apis/serpapi.py:17-21`) | Failures look like "no results"; nobody can tell a real empty search from an outage; settings hidden behind import-time singleton | Surface an explicit degraded result (type/error) and inject the client + key; keep empty-vs-error distinct | Moderate (half day) | F4, testability |
| F10 | MEDIUM | Persisted `package` truncates resources to 3 but the LLM prompt renders the full list (`src/pipeline.py:171-176` vs `:178-183`) | The email can reference an item that is not persisted in `package_json`; history is not a faithful record of what was sent | Slice before prompting or persist the rendered set | Quick (< 1 hour) | — |
| F11 | MEDIUM | `POST /trips` is open, unauthenticated, un-rate-limited, and `email` is unvalidated (`src/routers/trips.py:13-37`, `src/trip_store.py:18`) | Anyone can burn LLM/SerpAPI credits and send mail from the company address; invalid emails fail only in the background | Validate `EmailStr` at the boundary, add per-IP rate limiting, require an API key before the flow is public | Moderate (half day) | Production exposure |
| F12 | MEDIUM | Dead/incomplete features shipped in-tree: empty `src/knowledge.py`, unused Qdrant URL (`src/settings.py:27`), unused `trip_template.*`, no `/feedback` route despite `feedback` table (`schema.sql:21-28`) | Confusing scope; a reader can't tell what's real; someone will wire the wrong thing | Either implement or delete; scope creep is a design decision, document it | Quick (< 1 hour) | Clarity |
| F13 | LOW | Import-time side effects: `SYSTEM_PROMPT` read at import (`src/prompts/__init__.py:8`), email template read at import (`src/apis/email.py:15`), `_fail_fast()` runs at import (`main.py:75`) | Fails at startup by design, but import order becomes load-bearing; importing `src.prompts` for tests crashes without the file | Keep fail-fast but move it to `lifespan()`; read files lazily or explicitly | Quick (< 1 hour) | Testability |
| F14 | LOW | Production-bad defaults in settings: `reload: bool = True` (`src/settings.py:17`), placeholder default model `gpt-5.6-luna` (`src/settings.py:39`), Italian flag help strings (`main.py:31-33`) | A default-dirt deploy runs with reload and a wrong model name | Default `reload=False`, empty model defaults with `_fail_fast`, English help strings | Quick (< 1 hour) | Safe deploy |
| F15 | LOW | `schema.sql` mixes DDL and an inspection `SELECT` (`schema.sql:32-64`) | `psql -f schema.sql` executes a query mid-migration; not pure, not idempotent as written | Strip the SELECT; make the file pure DDL | Quick (< 1 hour) | Migrations |

---

## 3. Detail: The Three Most Impactful Findings

### F1 — Durable execution substrate (Before/After)

Today the "job queue" is Redis state + a lock, but execution lives inside the HTTP
process:

```python
# BEFORE: src/routers/trips.py — workflow fused with request path
@router.post("", response_model=TripResponse)
async def create_trip(payload, background_tasks, ...):
    trip = await store.create(payload)
    orchestrator = TripOrchestrator(store=store, llm_client=..., trip_id=trip.id, ...)
    background_tasks.add_task(orchestrator.run)   # dies with the process
    return trip
```

After separating request path from workflow path, the existing `claim()` lock
becomes the worker lease (it is already the right primitive):

```python
# AFTER: request path only enqueues
@router.post("", response_model=TripResponse)
async def create_trip(payload: TripCreateRequest, store=Depends(get_trip_store)):
    trip = await store.create(payload)
    await store.enqueue(trip.id)                 # Redis Stream XADD / ARQ
    return trip

# worker.py — a separate process, run alongside the API
async def worker_main():
    while True:
        trip_id = await queue.dequeue()          # XREADGROUP BLOCK
        orchestrator = TripOrchestrator(...)
        await orchestrator.run()                 # claim() gives idempotency
```

This preserves the layered structure and turns the existing `claim`/`SET NX EX`
from a nice-to-have into the concurrency primitive it was designed to be. It
unblocks horizontal scale-out and makes the pipeline testable without HTTP.

### F2 — Transactional outbox for email + history

```python
# BEFORE: src/pipeline.py — external I/O before durable record
await self._send_email(trip, ...)              # Resend call
await self._save_history(trip, ...)            # Postgres insert — can fail after the send
```

```python
# AFTER: persist intent + package + email_content atomically, then dispatch
# 1) one transaction writes trip row + outbox event
await self._db.save_trip_and_outbox(trip, intent, package, email_content)
# 2) a dispatcher drains outbox -> Resend -> marks status=sent
await self._db.dispatcher_drain()
```

`package_json` on `trip_history` already gives you step 1's payload with no new
store. This makes the record the cause and the email the effect, so retries are
safe and the audit trail is truthful.

### F4 — Test seams (DIP, applied not preached)

```python
# BEFORE: src/apis/llm.py — SDK client constructed inside, untestable
class AnthropicClient:
    def __init__(self, api_key: str, model: str, system_prompt=None):
        self._client = AsyncAnthropic(api_key=api_key)   # hard-wired

# AFTER: inject a client factory — the Protocol stays the contract
class AnthropicClient:
    def __init__(self, api_key: str, model: str, system_prompt=None,
                 client: AsyncAnthropic | None = None):
        self._client = client or AsyncAnthropic(api_key=api_key)
```

The same one-line change applies to `OpenAIClient`, `OllamaClient`, `EmailSender`,
and the SerpAPI tools (inject `serpapi.Client` + key instead of
`get_settings()` inside `search()`). None of these is "abstract interface on every
class" — it is one optional constructor parameter per adapter, and it unlocks the
entire test suite.

---

## 4. SOLID Analysis (Applied, Not Preached)

- **SRP** — Mostly good. `TripOrchestrator` is the main offender: it orchestrates,
  renders prompt blocks (`_render_*`), holds email copy constants (`HONEST_NOTE`,
  `CTA` at `src/pipeline.py:22-24`), and builds the plain-text body
  (`_compose_body_text`). Copy and rendering are presentation concerns leaking
  into the orchestrator. Extract `EmailRenderer`/move constants to the email
  module.
- **OCP** — The LLM layer is genuinely open (`LLMClient` Protocol +
  factory at `src/dependencies.py:24-45`; a 4th provider is additive). The search
  tools are **not**: pipeline imports `src.tools.flights/maps/places` concretely
  and calls module functions, so a new source (e.g. a direct airline API) means
  editing pipeline call sites.
- **LSP** — The three `*Client` classes each honor the Protocol's contract
  (structured, validated extraction). No violations observed.
- **ISP** — `LLMClient.extract[T]` is a single-method interface — correct. The
  orchestration-side is where ISP bites: `TripOrchestrator.__init__` takes seven
  positional dependencies; better to pass one composed "workflow context" or
  grow it via a single `Trip` aggregate.
- **DIP** — Mixed. High-level code depends on the `LLMClient` abstraction (good)
  but on the concrete `Database`, concrete module-level tools, and a global
  `get_settings()` singleton (bad). The cheap fix is injection at the points that
  vary: tools, database, and SDK clients.

---

## 5. Anti-Patterns & Over-Engineering Flags (what to NOT do)

- **No microservices.** Correct call at this scale — a single well-layered
  monolith with a worker process is the right shape. Do not fragment.
- **No repository pattern.** `trip_history` is one table with one consumer;
  wrapping it in a repository abstraction would be over-engineering. The existing
  `Database` class with a couple of methods is the right size. Add interfaces only
  when a second implementation appears.
- **No CQRS/event-driven.** The single producer/consumer does not need it; F2's
  outbox is the minimal correctness mechanism, not an event bus.
- **Red flag to avoid: abstract interface on every class.** Use the injection
  seams from F4 for what *varies* (LLM providers, search providers, SDK clients);
  do not wrap `TripStore` or `Database` in interfaces until there are two
  implementations.

---

## 6. ADRs (retrofitted for the decisions that actually shaped the system)

### ADR-001: LLM provider abstraction via Protocol

- **Status**: Accepted (implemented `src/apis/llm.py:14-17`)
- **Context**: Three providers (Anthropic/OpenAI/Ollama) with different API shapes
  and a local-testing path via Ollama.
- **Decision**: A structural `Protocol` + factory in `dependencies.py`, chosen by
  CLI flag. Tool-call schema is generated from pydantic models
  (`src/tools/__init__.py`), keeping the LLM contract honest.
- **Alternatives**: A single provider only (rejected — local dev needs Ollama);
  class hierarchy with ABC (rejected — Protocol + factory is less ceremony).
- **Consequences**: Providers are swappable and the orchestration is provider-
  agnostic; adds a small factory in DI. **Revisit when** a provider needs
  streaming or multi-turn, or the tool schema diverges per provider.

### ADR-002: Redis hash as the operational trip state

- **Status**: Accepted for prototype; **should be reconsidered** (F3)
- **Context**: Job state with TTL, lock-based idempotency, no durable execution.
- **Decision**: Redis hash `trip:{id}` + `SET NX EX` lock (`src/trip_store.py:41-83`).
- **Consequences**: Cheap, fast status reads; but state is ephemeral (24h TTL)
  and the lock lease is shorter than worst-case runs (F7). Postgres is the only
  durable record. **Revisit when** a second worker process or real retention is
  needed — that is F1/F3.

### ADR-003: Monolith + background task (no queue)

- **Status**: Accepted for prototype; **deprecated by F1**
- **Context**: Single process, demo scale, simplest thing that works.
- **Decision**: `BackgroundTasks` in the same process as the API.
- **Consequences**: Zero infra; loses in-flight work on restart; no retries; not
  horizontally scalable. **Revisit now** — this is the top finding.

---

## 7. System Design Checklist

**Decomposition**
- [x] Bounded contexts are clear: trips (HTTP/store), workflow (orchestrator),
      capabilities (tools), adapters (apis), prompts.
- [x] Contracts between modules are pydantic models (`TripIntent`, `EmailContent`)
      for the LLM boundary; dicts everywhere else — **weak spot** (F9/F10).
- [ ] Map data ownership: who is the source of truth for a trip? Undefined (F3).

**Boundaries & Coupling**
- [x] No circular imports; dependencies point inward.
- [x] Synchronous consistency only where required (request/response).
- [ ] Async path is not durable (F1); no redelivery.
- [ ] Components not testable in isolation (F4/F5).

**Evolution Planning**
- [ ] Adding a new search tool touches pipeline call sites (OCP gap).
- [ ] Adding a feedback endpoint touches schema + router only — good.
- [ ] Can the email copy change without touching code? Only via template file —
      good; but `HONEST_NOTE`/`CTA` are in Python (F6).

**Operational Concerns**
- [ ] No container, no CI, no migrations tooling, no proxy/TLS, no monitoring.
- [ ] Logs are rich but unstructured; no request/trip-level trace id propagation.
- [ ] Rollback = redeploy previous commit; in-flight jobs lost (F1).

---

## 8. Strengths (to preserve)

| # | Strength | Where |
|---|---|---|
| 1 | Clean inward layering, no circular imports | `src/` structure |
| 2 | LLM abstraction is the right size (Protocol, not over-abstraction) | `src/apis/llm.py:14-17` |
| 3 | The `SET NX EX` claim lock is the correct primitive for the future worker pool | `src/trip_store.py:80-83` |
| 4 | Structured pydantic contracts for LLM I/O — extraction is validated | `src/models.py` |
| 5 | Degradation is deliberate for SerpAPI (empty lists + `NoResourcesError`) | `src/pipeline.py:158-169` |
| 6 | Monolith-with-clean-boundaries is the right call at this scale | — |
| 7 | Per-provider model/env wiring fails fast at startup | `main.py:68-75` |

---

## 9. Next Steps

1. **F1 first** — durable queue + worker; it is the keystone that F2/F3/F7 build on.
2. **F4 seams + F5 tests** — do these together, before touching pipeline logic, so
   the rest of the refactor has a safety net.
3. **F3 source of truth** — fold `status` into Postgres once F1 lands.
4. **F2 outbox** — only after F1, since the outbox needs the durable substrate.
5. **F11 gate the endpoint** — do before any real traffic.
6. Clean up F8/F10/F12/F13/F14/F15 opportunistically — each is under an hour.
7. Re-audit after the keystone lands; verify structural changes with build gates
   and git checkpoints per round (per the destructive-operations protocol).
