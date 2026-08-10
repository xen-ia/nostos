# νόστος-ξενία

```md
nostos/
├── main.py
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
    ├── tools/
    ├── prompts/
    └── routers/
```

### Ruoli principali
- `main.py` — entrypoint FastAPI; il provider LLM e i timeout si scelgono da CLI: `uv run main.py [--claude|--gpt|--ollama] [--serpapi-timeout S] [--email-timeout S]`.
- `src/pipeline.py` — `TripOrchestrator`: estrae l'intent via LLM → raccoglie voli/POI/alloggi da SerpAPI → compone e invia l'email.
- `src/apis/` — provider esterni: `llm.py` (protocol + client Anthropic/OpenAI/Ollama), `email.py` (Resend), `serpapi.py` (client condiviso).
- `src/tools/` — capacità della pipeline: schema di estrazione da modello pydantic (`__init__.py`) e ricerche `flights`/`maps`/`places`.
- `src/prompts/system_prompt.md` — voce editoriale di Xen-IA, unica fonte delle regole per i modelli.

### Quickstart
```bash
cp .env.example .env
```

### Design del sistema

Flusso (in background dopo `POST /trips`): form → `TripStore` (Redis) → estrazione intent via LLM → ricerche SerpAPI (voli/POI/alloggi) → composizione email via LLM → invio Resend → storico su Postgres.

- **FastAPI (`main.py`)** — API + lifespan (connessioni Redis/Postgres). Provider LLM e timeout selezionati da CLI: `--claude|--gpt|--ollama`, `--serpapi-timeout`, `--email-timeout`.
- **Redis** — job store dei trip: creazione, stato (`PENDING`/`RUNNING`/`ERROR`/…) e lock atomico `SET NX EX` contro esecuzioni doppie.
- **Postgres** — `trip_history`: storico delle email inviate (intent, pacchetto ricercato, subject/body).
- **LLM (`LLMClient` protocol)** — estrazione strutturata via tool-call su modelli pydantic (`TripIntent`, `EmailContent`). Implementazioni: `AnthropicClient`, `OpenAIClient` (Responses API), `OllamaClient`; provider scelto da CLI, modello fissato in settings.
- **SerpAPI** — ricerca voli (`google_flights`), POI (`google_maps`), alloggi (`google_hotels`), con timeout configurabile. Categoria senza risultati validi → scartata; se tutte vuote, il trip si interrompe senza inviare email.
- **Resend** — invio email transazionale (`EmailSender`), timeout configurabile.
- **Prompts (`system_prompt.md`)** — voce editoriale Xen-IA, unica fonte delle regole; i prompt per-task apportano solo il contesto dati.
- **Qdrant** — previsto per knowledge base/RAG (embedding dedicato, separato dall'LLM); non ancora integrato.