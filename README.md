# ξενία-νόστος

```md
nostos/
├── main.py                   # FastAPI app + lifespan (apre/chiude redis, postgres, qdrant) + include_router
├── docker-compose.yml        # redis + postgres + qdrant, un comando per tutta l'infra locale
├── pyproject.toml
├── uv.lock
├── .env.example
├── .python-version
├── .gitignore
├── README.md
│
├── docs/
│   └── index.html
│
├── tests/
│   └── test_trip_store.py    # solo il lock atomico, il punto più delicato oggi
│
└── src/
    ├── settings.py           # config, un file, tutta la verità
    ├── dependencies.py       # Depends(): redis, postgres session, qdrant, trip_store, orchestrator
    │
    ├── trip_store.py         # TripStatus, TripCreateRequest/Response, TripStore (Redis)
    ├── database.py           # engine + modelli SQLAlchemy (TripHistory, Feedback, Destination) + query dirette
    ├── knowledge.py          # qdrant client + embedding (fastembed) + retrieval — un file, si spacca quando cresce
    │
    ├── pipeline.py           # TripOrchestrator
    ├── bases/
    │   └── orchestrator.py
    │
    ├── apis/                 # APIs 
    │   ├── flights.py
    │   ├── maps.py
    │   ├── places.py
    │   ├── llm.py            
    │   └── email.py
    │
    ├── routers/
    │   ├── trips.py
    │   └── feedback.py
    │
    ├── prompts/
    └── tools/
```

### Quickstart
```bash
cp .env.example .env
```