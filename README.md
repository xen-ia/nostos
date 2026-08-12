# νόστος-ξενία

```md
nostos/
├── main.py
├── schema.sql
├── docs/
│   └── index.html
└── src/
    ├── settings.py
    ├── dependencies.py
    ├── models.py
    ├── trip_store.py
    ├── database.py
    ├── pipeline.py
    ├── apis/
    │   ├── llm.py
    │   ├── email.py
    │   └── serpapi.py
    ├── tools/
    │   ├── flights.py
    │   ├── maps.py
    │   └── places.py
    ├── prompts/
    ├── routers/
    │   └── trips.py
    ├── templates/
    └── knowledge/
```

### Quickstart
Fill in your API keys for the models (`anthropic` and/or `openai`) and for the services (`resend`, `serpapi`) — the latter offers a usable free plan.
```bash
cp .env.example .env
```

Then run the server:
```bash
uv run main.py [--claude | --gpt | --ollama] --serpapi-timeout 180 --email-timeout 180
```

and send a request from the mock frontend at [https://xen-ia.github.io/nostos/](https://xen-ia.github.io/nostos/).

### Locale con Ollama e Qwen3-30B-A3B

The `--ollama` provider runs a local model through Ollama. The lightweight default is `qwen2.5:3b-instruct`; for a far better extraction/composition quality you can use Qwen3-30B-A3B (MoE, 3.3B active):

```bash
ollama pull qwen3:30b-a3b-instruct-2507-q4_K_M
export NOSTOS_OLLAMA_MODEL=qwen3:30b-a3b-instruct-2507-q4_K_M
uv run main.py --ollama --serpapi-timeout 180 --email-timeout 180
```

Notes:
- The model is ~19GB. On 8GB-RAM machines it runs via SSD streaming/swap: each LLM extraction can take minutes, so check `GET /trips/{id}` instead of expecting a fast email. Keep the context small (`NOSTOS_OLLAMA_NUM_CTX=8192` default).
- Qwen3 thinking mode is disabled in the client (`think=False`) so structured JSON extraction stays clean.

#### CLI Test
Instead, you can test locally by sending a curl request
```bash
curl -s -X POST http://localhost:3072/trips \
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
curl -s -X POST http://localhost:3072/trips \
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
- `main.py` — FastAPI entrypoint; the LLM provider and timeouts are chosen from the CLI: `uv run main.py [--claude|--gpt|--ollama] [--serpapi-timeout S] [--email-timeout S]`.
- `src/pipeline.py` — `TripOrchestrator`: extracts the intent via LLM → gathers flights/POIs/accommodations from SerpAPI → composes and sends the email.
- `src/apis/` — external providers: `llm.py` (protocol + Anthropic/OpenAI/Ollama clients), `email.py` (Resend), `serpapi.py` (shared client).
- `src/tools/` — pipeline capabilities: pydantic extraction schema (`__init__.py`) and `flights`/`maps`/`places` searches.
- `src/prompts/system_prompt.md` — Xen-IA editorial voice, the single source of rules for the models.
- `src/routers/trips.py` — REST API: `POST /trips` (creates the trip and starts the background flow), `GET /trips/{id}` (status).
- `schema.sql` — Postgres schema: `trip_history` (email history) and `feedback` (ratings).
- `docs/index.html` — mock frontend

### System design

Flow (in the background after `POST /trips`): form → `TripStore` (Redis) → intent extraction via LLM → SerpAPI searches (flights/POIs/accommodations) → email composition via LLM → Resend send → Postgres history.

- **FastAPI (`main.py`)** — API + lifespan (Redis/Postgres connections). LLM provider and timeouts selected from the CLI: `--claude|--gpt|--ollama`, `--serpapi-timeout`, `--email-timeout`.
- **Redis** — trip job store: creation, status (`PENDING`/`RUNNING`/`ERROR`/…) and atomic `SET NX EX` lock against double execution.
- **Postgres** — `trip_history`: history of sent emails (intent, searched package, subject/body) + `feedback`; schema in `schema.sql`.
- **LLM (`LLMClient` protocol)** — structured extraction via tool-call on pydantic models (`TripIntent`, `EmailContent`). Implementations: `AnthropicClient`, `OpenAIClient` (Responses API), `OllamaClient`; provider chosen from the CLI, model fixed in settings.
- **SerpAPI** — searches flights (`google_flights`), POIs (`google_maps`), accommodations (`google_hotels`), with a configurable timeout. Category without valid results → discarded; if all are empty, the trip stops without sending the email.
- **Resend** — transactional email sending (`EmailSender`), configurable timeout.
- **Prompts (`system_prompt.md`)** — Xen-IA editorial voice, the single source of rules; per-task prompts only bring in the data context.