# νόστος-ξενία

```md
nostos/
├── main.py                   # FastAPI app + lifespan (apre/chiude solo redis) + include_router
├── pyproject.toml
├── uv.lock
├── .env.example
├── .python-version
├── .gitignore
├── README.md
│
├── docs/
│   └── index.html            # frontend mock (form viaggio + POST /trips)
│
└── src/
    ├── settings.py           # config via pydantic-settings, prefisso NOSTOS_
    ├── dependencies.py       # Depends(): redis, trip_store, llm_client, email_sender
    │
    ├── trip_store.py         # TripStatus, TripCreateRequest/Response, TripStore (Redis)
    ├── database.py           # placeholder per engine/modelli SQLAlchemy (non ancora implementato)
    ├── knowledge.py          # placeholder per qdrant/embedding (non ancora implementato)
    │
    ├── pipeline.py           # TripOrchestrator: estrae intent LLM → compone pacchetto → invia email
    ├── bases/
    │   └── orchestrator.py   # BaseOrchestrator (ABC)
    │
    ├── apis/                 # integrazioni esterne
    │   ├── flights.py        # stub di ricerca voli
    │   ├── maps.py           # stub di ricerca punti di interesse
    │   ├── places.py         # stub di ricerca alloggi/esperienze
    │   ├── llm.py            # AnthropicClient (extract_json / generate_text)
    │   └── email.py          # EmailSender via Resend
    │
    ├── routers/
    │   └── trips.py          # POST /trips (crea + run orchestrator), GET /trips/{id}
    │
    ├── prompts/
    │   └── system_prompt.md
    └── tools/
```

### Quickstart
```bash
cp .env.example .env
```