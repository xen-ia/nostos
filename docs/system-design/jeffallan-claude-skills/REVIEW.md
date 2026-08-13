# Review — nostos (jeffallan/claude-skills, fastapi-expert)

Review del design di sistema e dell'architettura software di nostos, condotta con la
skill `fastapi-expert` (sezioni 1–7) e con la skill `api-designer` (sezione 8).
L'analisi è focalizzata sull'app FastAPI (`main.py`, `src/`, `schema.sql`) e sul suo
contratto API (endpoint, schemi, error model, versioning). Il documento è scritto per
essere **evolutivo, non distruttivo**: ogni finding cita `file:line`, indica severità,
impatto e fix concreto.

**Data audit**: 2026-08-13 — **Scope**: `main.py`, `src/` (routers, dependencies,
trip_store, models, pipeline, apis, tools, prompts, database, settings), `schema.sql`,
`docs/index.html`, `pyproject.toml`.

---

## Verdetto

```
FastAPI Review Score
====================

Dependency Injection  ███████░░░  [Good] - DI pulita via Depends, override-abile nei test
Lifespan/Startup      ████░░░░░░  [Needs Work] - init import-time + argparse modulare, no retry/healthcheck
Pydantic Schemas      ████░░░░░░  [Needs Work] - validazione insufficiente (email, date, length)
Endpoint/REST         ███░░░░░░░  [Needs Work] - status code, versioning, auth/rate-limit assenti
Async Execution       ██░░░░░░░░  [Critical] - BackgroundTasks in-process per workflow a lunga durata
Error Handling        ████░░░░░░  [Needs Work] - exception strings esposte via API, no handler custom
OpenAPI/Docs          █████░░░░░  [OK] - docs auto-generate corrette, surface non versionata
Testability           ██░░░░░░░░  [Critical] - zero test, ma seams DI già pronte
```

**Giudizio complessivo**: l'app FastAPI è **ben strutturata come monolite a livelli**
(dipendenze verso l'interno, astrazione LLM via Protocol, schemi pydantic ai confini) e
le fondamenta per renderla testabile esistono già (DI override-abile, `TripOrchestrator`
costruito via costruttore). **Non è però pronta per il deploy**: il workflow gira
in-process con `BackgroundTasks` (non durevole), la validazione dei payload è troppo
debole per un'API che brucia costi LLM/SerpAPI/Resend a ogni chiamata, non c'è auth né
rate limiting, e non esiste alcun test. Il refactor necessario è **evolutivo**: le seam
sono già lì, mancano i test e la separazione request-path / workflow-path.

---

## 1. Contesto e requisiti (restatement)

- **Cosa fa**: `POST /trips` accetta una richiesta di viaggio → LLM estrae l'intent →
  SerpAPI cerca voli/POI/alloggi (in parallelo) → LLM compone un'email → Resend la invia
  → Postgres salva lo storico. `GET /trips/{trip_id}` espone lo stato. La risposta HTTP è
  immediata, il flusso gira in background.
- **Scale target**: demo/pilota. Singolo processo, singola istanza, poche decine di
  richieste, workflow di minuti, **costi reali per esecuzione** (LLM + SerpAPI + email).
- **Vincoli operativi**: nessun SLA, nessun CI, nessun container, `schema.sql` applicato a
  mano, nessuna migrazione.
- **Punti di accoppiamento**: request-path e workflow-path convivono nello stesso processo
  (`background_tasks.add_task` in `src/routers/trips.py:35`). È la decisione più
  portante del sistema e la radice dei finding critici.
- **Pattern di cambiamento comune**: aggiungere un tool di ricerca, aggiungere un provider
  LLM, cambiare copia/template email, aggiungere endpoint feedback. Ciascuno dovrebbe
  essere una modifica a un file solo.

---

## 2. Architettura in breve (com'è oggi)

```
docs/index.html ──POST JSON──▶ POST /trips (src/routers/trips.py)
                                 │  store.create() → Redis hash trip:{id}
                                 │  background_tasks.add_task(orchestrator.run)
                                 ▼
                      TripOrchestrator.run (src/pipeline.py)
                        │ 1. claim lock (SET NX EX, TTL 300s)
                        │ 2. intent via LLM (TripIntent)
                        │ 3. asyncio.gather(SerpAPI flights + maps + places)
                        │ 4. email via LLM (EmailContent)
                        │ 5. Resend send
                        │ 6. Postgres save_trip_history
                        ▼
                     GET /trips/{id} → stato da Redis (TTL 24h)

Componenti:
  main.py            entrypoint FastAPI, lifespan (Redis + Postgres pool), CORS
  src/routers/       surface HTTP (2 endpoint)
  src/dependencies   factory DI (LLM provider, store, database, timeout)
  src/trip_store     stato operativo in Redis (hash + lock)
  src/pipeline       orchestratore del workflow
  src/apis/          adapter esterni: LLM (3 provider), email (Resend), SerpAPI
  src/tools/         capabilities di ricerca (flights, maps, places)
  src/prompts/       prompt system + costruttori prompt
  src/models.py      schemi pydantic ai confini LLM (TripIntent, EmailContent)
  src/database.py    persistenza Postgres (trip_history)
```

---

## 3. Findings table (FastAPI)

| ID | Severità | Finding | Impatto | Fix | Effort |
|----|---------|---------|---------|-----|--------|
| FA-1 | 🔴 CRITICAL | Workflow a lunga durata via `BackgroundTasks` in-process (`src/routers/trips.py:35`) | Crash/deploy/riavvio perdono i trip in volo (stuck `PENDING`/`RUNNING`); nessun redelivery, nessuno scale-out | Coda job persistente (Redis Stream/ARQ) + worker separato; riusare `claim()` come lease | Significativo |
| FA-2 | 🔴 CRITICAL | Nessun timeout sulle chiamate LLM (`src/apis/llm.py:27,46,66`) | Un hang del provider blocca il job per sempre; con il lock TTL 300s (`src/pipeline.py:32`) può produrre email doppie | `timeout=` sui client o `asyncio.wait_for`; errori tipizzati + retry | Veloce |
| FA-3 | 🔴 CRITICAL | Nessuna auth né rate limiting sugli endpoint (`src/routers/trips.py`) | API aperta: chiunque brucia costi LLM/SerpAPI/Resend e legge PII (`email`, `free_text`) conoscendo l'UUID | API key / sessione + rate limit per IP/email (slowapi o Redis) prima del go-live | Moderato |
| FA-4 | 🟠 HIGH | `TripCreateRequest` valida troppo poco (`src/trip_store.py:17-27`): `email: str`, date `str`, no `max_length` | Email invalide falliscono solo a fine pipeline (costi bruciati); date non verificate (`end < start`) | `EmailStr`, date ISO validate (`field_validator` + `model_validator` end>=start), `max_length` su `free_text` | Veloce |
| FA-5 | 🟠 HIGH | Gli schemi vivono in `src/trip_store.py` (layer di storage), non in un modulo schemi dedicato | Il contratto API è accoppiato allo store; il frontend dipende da un dettaglio di implementazione | Estrarre `src/schemas.py` (o `src/api/contracts.py`); lo store importa lo schema | Veloce |
| FA-6 | 🟠 HIGH | `GET /trips/{trip_id}` espone `result=str(exc)` (`src/pipeline.py:83`, `src/trip_store.py:34`) | Dettagli interni (URL provider, stati HTTP) filtrati al client; information disclosure | Log completo server-side con `trip_id`, esporre solo `error_code` tipizzato | Veloce |
| FA-7 | 🟠 HIGH | Zero test e seams di testabilità non sfruttate (`pyproject.toml`, nessuna dir `tests/`) | Refactor senza rete di sicurezza; regressioni nella money-path passano in produzione | pytest + pytest-asyncio + `app.dependency_overrides` + fakeredis | Moderato |
| FA-8 | 🟠 HIGH | `argparse` a livello di modulo + `reload=True` di default (`main.py:26-50`, `src/settings.py:17`) | `uvicorn main:app --workers N` esegue argparse due volte; reload in prod = job persi; provider via CLI invece di env | Parsing in `run()`/`__main__`, `reload=False` in prod, `NOSTOS_LLM_PROVIDER` | Veloce |
| FA-9 | 🟡 MEDIUM | `POST /trips` senza `status_code=201`, surface non versionata, nessun prefisso `/api/v1` | Semantica REST debole; evolvere l'API dopo richiede breaking change | `status_code=status.HTTP_201_CREATED`, prefisso `/api/v1`, ADR di versioning | Veloce |
| FA-10 | 🟡 MEDIUM | Lifespan senza retry/backoff e senza `/healthz`/`/readyz` (`main.py:86-87`) | Se Redis/PG giù al boot l'app muore; orchestratori non sanno se è pronta | Retry con backoff alla creazione pool + endpoint di liveness/readiness | Moderato |
| FA-11 | 🟡 MEDIUM | `_to_response` ricostruisce manualmente il modello da dict con tipi fragili (`src/trip_store.py:91-107`, `:100`) | `str(bool) == "True"` fragile; mapping manuale che può divergere dallo schema | Salvare i campi tipizzati (o JSON intero) e validare con `model_validate` | Veloce |
| FA-12 | 🟡 MEDIUM | Nessun exception handler custom; `TripNotFoundError` → 404 ma il resto sono 500 generici | Errori non tipizzati, niente mapping coerente dei 422/500 | Handler globali per 422/500 + `detail` coerente | Veloce |
| FA-13 | 🟡 MEDIUM | `get_llm_client` ricostruisce il client a ogni request (`src/dependencies.py:24-45`) | Costruzione ripetuta dei client SDK (trascurabile ma evitabile) | Costruire in `lifespan()` e salvare in `app.state`, esporre via dep | Veloce |
| FA-14 | 🟡 MEDIUM | `allow_headers=["*"]` e metodi hard-coded in CORS (`main.py:97-103`) | Origin di produzione non configurabile di default; restringere headers/methods | Origin esplicite via env, headers/methods minimi | Veloce |
| FA-15 | 🔵 LOW | Import-time side effects: `SYSTEM_PROMPT` e template email letti all'import (`src/prompts/__init__.py:8`, `src/apis/email.py:15`) | Importare il modulo per test fallisce senza il file; ordine di import load-bearing | Lettura lazy o esplicita in `lifespan()` | Veloce |
| FA-16 | 🔵 LOW | Mix stile: `Optional[X]` vs `X | None`, `dict` come contratto di ritorno (`src/pipeline.py:139,192`) | Lie di tipo (`tuple[dict, dict]` per un 4-tuple); incoerenza Pydantic V2 | `X | None` ovunque, dataclass o tupla annotata correttamente | Veloce |

---

## 4. Sezione FastAPI (review dedicata)

### 4.1 Struttura dell'app e lifecycle

`main.py` è un entrypoint pulito: lifespan apre Redis + pool Postgres, installa CORS,
include il router `trips`. Tre problemi strutturali:

1. **Config a livello di modulo** (`main.py:26-50`): `_parse_args()` e `_fail_fast()` girano
   all'import. Qualsiasi tool che importi `main:app` (uvicorn con `--workers`, test) ri-esegue
   argparse e può fallire. La scelta del provider LLM come **flag CLI** è una decisione di
   deploy-time codificata nel processo: in container è scomoda. Fix: parsing dentro `run()` /
   `if __name__ == "__main__"`, provider via `NOSTOS_LLM_PROVIDER`.

2. **Startup fragile** (`main.py:86-87`): `create_pool`/`from_url` senza retry, senza parametri
   (`min_size`, `max_size`, `command_timeout`). Con un orchestratore che riavvia va bene, ma
   oggi orchestratore non c'è. Nessun `/healthz` (liveness) né `/readyz` (Redis+PG up).

3. **`reload: bool = True` di default** (`src/settings.py:17`): in produzione un watcher di
   reload rende il deploy non deterministico e — combinato con FA-1 — perde i job in volo a
   ogni modifica file.

### 4.2 Dependency injection

La DI via `Depends` è il punto forte: ogni dipendenza è override-abile nei test con
`app.dependency_overrides` (vedi `src/dependencies.py`, `src/routers/trips.py`). Note:

- `get_llm_client` sceglie il provider a runtime dal flag CLI (`src/dependencies.py:24-45`):
  funziona, ma sposta una decisione di deploy-time nel codice (FA-8).
- `get_trip_store`, `get_database`, `get_email_sender` sono factory pulite; il pattern
  `Annotated` (consigliato dalla skill) non è usato, ma a 6 dipendenze per endpoint è
  accettabile — migliorabile con type-alias `Annotated[TripStore, Depends(get_trip_store)]`.
- I client SDK vengono ricostruiti a ogni request (FA-13): trascurabile, ma spostare in
  `app.state` nell'lifespan è gratis.

### 4.3 Schemi Pydantic e validazione

Punti forti: `Literal` tipizzati su `travelers_type`/`budget_range`, `ge=1` su
`travelers_count`, modelli ai confini LLM (`TripIntent`, `EmailContent`) ben descritti.

Criticità rispetto alle best practice della skill:

- `email: str` invece di `EmailStr` (`src/trip_store.py:18`) — primo fix da fare.
- `start_date`/`end_date` come `Optional[str]` senza formato né ordinamento: `end < start`
  fallisce solo a fine pipeline (`src/database.py:40`), dopo 2 chiamate LLM + 3 SerpAPI.
- `free_text` senza `max_length`: payload LLM e prompt crescenti = latenza e costo.
- Assenza di `field_validator`/`model_validator` e di `model_config` (es.
  `str_strip_whitespace=True`). Il fix è un puro cambio di schema, nessuna logica toccata.
- Gli schemi API vivono in `trip_store.py` (FA-5): separazione da fare per tenere il
  contratto HTTP indipendente dallo storage.

### 4.4 Endpoint e REST semantics

- `POST /trips` ritorna 200 di default: manca `status_code=201` (FA-9).
- Nessuna versione nell'URL (`/trips` invece di `/api/v1/trips`): la surface è implicitamente
  v1 senza strategia documentata.
- `GET /trips/{trip_id}` usa `HTTPException(404)` per "non trovato o scaduto": confla due
  casi (assenza reale vs TTL Redis scaduto) — con FA-1/FA-3 cambierà semantica.
- `TripResponse` espone `result` con la stringa dell'eccezione (FA-6).
- Nessun auth/rate-limit (FA-3): per un'API che **invia email brandizzate** e brucia costi,
  è il bloccante di produzione insieme a FA-1.

### 4.5 Esecuzione asincrona e workflow

Il pattern async è corretto dove usato (`asyncio.gather(..., return_exceptions=True)` per le
3 ricerche SerpAPI, `asyncio.to_thread` per SDK sincroni come resend/serpapi, `wait_for` per
i timeout su email/SerpAPI). Il problema è a monte:

- **`BackgroundTasks` non è un job queue** (FA-1). Vive nella memoria del worker che ha
  ricevuto la richiesta: crash, deploy o shutdown del lifespan (`main.py:89-92`) uccidono il
  job mentre usa pool già chiusi. Il lock `claim()` (`src/trip_store.py:80-83`) è il mattone
  giusto per un futuro worker pool — è già l'astrazione di lease — ma oggi non ha un
  consumatore stabile.
- **LLM senza timeout** (FA-2): `messages.create`/`responses.create`/`chat` non hanno
  timeout; con lock TTL 300s un retry riesegue il trip → email doppia.
- **Ordine email→storico fragile** (`src/pipeline.py:75-78`): se l'insert Postgres fallisce
  dopo l'invio, l'email esiste ma lo storico no. Fix: persistire intent+package+contenuto in
  Postgres prima dell'invio, poi `status=sent`.

### 4.6 Error handling

- Nessun exception handler custom (FA-12): gli errori non-`TripNotFoundError` diventano 500
  generici di Starlette.
- `result=str(exc)` esposto via API (FA-6).
- `EmailSendError` e `NoResourcesError` sono ben tipizzate ma non hanno un mapping HTTP.
- Il logging (`main.py:18`) usa `RichHandler(markup=True)`: i valori utente con tag Rich
  corrompono i log (log injection), e `intent.model_dump()` a `pipeline.py:70` logga PII.

### 4.7 OpenAPI / Docs

- `/docs` e `/openapi.json` ci sono di default e sono corretti: schemi derivati da
  `TripCreateRequest`/`TripResponse`, tags `trips`.
- Manca una strategia di versioning e non c'è un contratto formalizzato oltre il default.
- I `description` dei campi di `TripIntent`/`EmailContent` arricchiscono il JSON schema
  (utile per i tool LLM e per i docs).

### 4.8 Testabilità

La buona notizia: **le seams esistono già**. `TripOrchestrator` riceve store/llm/email/db via
costruttore (`src/pipeline.py:42-58`), `LLMClient` è un Protocol (`src/apis/llm.py:14-17`),
`TripStore` ha un'interfaccia piccola e statica (compatibile con fakeredis), le factory DI
sono override-abili. Serve solo:

1. `uv add --dev pytest pytest-asyncio pytest-cov fakeredis`
2. `tests/unit` (modelli, `_compose_body_text`, normalizzatori tool, `_simplify`), `tests/integration` (TripStore su fakeredis, `TripOrchestrator.run` con fake LLM/SerpAPI/email), `tests/e2e` (TestClient con `dependency_overrides`).
3. Un CI che esegua `uv run pytest`.

Bloccanti: `main.py` esegue argparse/`_fail_fast` all'import (FA-8), e `src/prompts` legge il
file a import-time (FA-15) — entrambi vanno sistemati prima di scrivere i test.

---

## 5. Cosa NON fare (anti-pattern)

- **Niente microservizi**: un monolite a livelli + worker è la forma giusta a questa scala.
- **Niente repository pattern**: `trip_history` è una tabella con un consumer; il `Database`
  attuale è la dimensione giusta.
- **Niente CQRS/event bus**: il problema di consistenza (FA-2 ordine) si risolve con un
  outbox minimale o riordinando le scritture, non con un bus eventi.
- **Non astrarre ogni classe**: aggiungi injection seams solo dove le cose *variano*
  (provider LLM, provider di ricerca, client SDK). `TripStore` e `Database` non hanno bisogno
  di interfacce finché non c'è una seconda implementazione.

---

## 6. Punti di forza (da preservare)

| # | Punto | Dove |
|---|-------|------|
| 1 | DI pulita via `Depends`, override-abile nei test | `src/dependencies.py`, `src/routers/trips.py` |
| 2 | `LLMClient` come Protocol: orchestrazione agnostica rispetto al provider | `src/apis/llm.py:14-17` |
| 3 | Modelli pydantic come contratto tra LLM e pipeline (tool-call vincolato a schema) | `src/models.py`, `src/tools/__init__.py` |
| 4 | Lock `SET NX EX` come primitive di lease per il futuro worker pool | `src/trip_store.py:80-83` |
| 5 | `asyncio.gather(return_exceptions=True)` per parallelizzare con degradazione | `src/pipeline.py:144` |
| 6 | `NoResourcesError` = fallimento onesto (no email senza risorse reali) | `src/pipeline.py:158-169` |
| 7 | Escape HTML su tutte le variabili LLM nel template email (anti-XSS) | `src/apis/email.py:49-71` |
| 8 | Timeout e `to_thread` gestiti correttamente dove già presenti (email, SerpAPI) | `src/apis/email.py:84`, `src/apis/serpapi.py:23` |
| 9 | Query SQL parametrizzate, nessun input utente in query | `src/database.py` |
| 10 | `Literal`/`ge=1` sui campi whitelisted | `src/trip_store.py:23-25` |

---

## 7. Piano di priorità

**Fase 1 — Bugfix rapidi (mezza giornata):**
1. FA-4: validazione schemi (EmailStr, date, max_length) — puro cambio di schema.
2. FA-2: timeout su tutte le chiamate LLM.
3. FA-6/FA-12/AD-2: exception handler custom → `application/problem+json`, no `str(exc)` esposto.
4. FA-8/FA-15: entrypoint pulito, `reload=False`, lettura file esplicita.

**Fase 2 — Contratto API + separazione request-path/workflow-path (2–3 giorni):**
5. AD-1/AD-10: `POST /trips` → 202 + `Location` + state machine documentata.
6. FA-1: worker dedicato + coda (si riusa `claim()` come lease) — la chiave di volta.
7. FA-2 ordine: persistenza prima dell'invio email.
8. FA-3: auth minima + rate limiting prima di qualsiasi traffico reale (AD-3, AD-5 col versioning).
9. AD-4: Idempotency-Key su POST.

**Fase 3 — Operabilità e test (2–3 giorni):**
10. FA-10: `/healthz` + `/readyz` + retry startup (AD: contratti operativi).
11. FA-7: suite pytest + CI + contract test col frontend (AD-5: redocly lint).
12. FA-9/FA-14: versioning `/api/v1` + CORS di produzione.
13. AD-7: endpoint feedback + AD-8: request_id.

---

## 8. API Design (review dedicata, skill `api-designer`)

Analisi del contratto API dell'intera app e delle sue componenti. L'API oggi è la superficie
di un **workflow asincrono** (submit → processing → email), non di un CRUD classico: questo
condiziona la semantica giusta per ogni endpoint. La sezione chiude con la specifica OpenAPI
3.1 target e il catalogo errori.

### 8.1 Stato attuale del contratto

| Endpoint | Metodo | Oggi | Consumatore |
|---|---|---|---|
| `/trips` | `POST` | Crea trip, lancia il background flow, risponde `TripResponse` (200) | `docs/index.html:1097-1105` |
| `/trips/{trip_id}` | `GET` | Stato del trip (PENDING/RUNNING/DONE/ERROR), 404 se assente/scaduto | non usato dal frontend |

Schemi: `TripCreateRequest` / `TripResponse` in `src/trip_store.py:17-34`. Naming in
`snake_case` coerente (unica eccezione: `free_text`, già così nel form). Il payload del
frontend (`docs/index.html:1083-1094`) è allineato a `TripCreateRequest`.

**Il problema di fondo**: l'API modella l'operazione sbagliata. `POST /trips` non crea
solo una risorsa, **accetta un lavoro asincrono** (LLM + SerpAPI + email, minuti di
esecuzione, costo reale). La semantica corretta è un **job queue / task pattern**: 202
Accepted + polling su un resource di stato. Oggi risponde 200 con la risorsa creata, e lo
stato arriva solo via polling su `/trips/{id}` — un ibrido che il client non consuma
nemmeno (il frontend si ferma al submit).

### 8.2 Resource model

```
POST /api/v1/trips ──▶ Trip (request + stato operativo) ──(dopo il processing)──▶ TripHistory (email inviata, package)
                          │                                                        ▲
                          │ GET /api/v1/trips/{trip_id}                             │
                          ▼                                                         │
                        Feedback (rating, 0..1 per trip) ───────────────────────────┘
```

| Resource | Proprietà chiave | Storage | Lifetime |
|---|---|---|---|
| `Trip` | id, status, request fields, result | Redis (`trip:{id}`, TTL 24h) | transitorio |
| `TripHistory` | id, email, dates, package_json, email_subject/body | Postgres (`trip_history`) | durevole |
| `Feedback` | trip_id, rating, note | Postgres (`feedback`) | durevole, **nessun endpoint** |

Oggi le prime due sono la **stessa risorsa** vista in due store (FA-3/F3): `Trip` è lo
stato operativo, `TripHistory` la storia durevole. L'API espone solo `Trip`, e dopo 24h
(`src/trip_store.py:70`) anche quel trip sparisce → 404 con dati ancora in DB.

### 8.3 Design target (endpoint proposti)

```
POST   /api/v1/trips                 → 202 Accepted + Location: /api/v1/trips/{id} + Idempotency-Key
GET    /api/v1/trips/{trip_id}       → 200 Trip (stato)  |  404 TripNotFound
POST   /api/v1/trips/{trip_id}/feedback → 201 Feedback    |  404 | 409 (già inviato)
GET    /api/v1/trips                 → 200 lista paginata (cursor) — quando esiste la lettura
GET    /healthz                      → 200 liveness
GET    /readyz                       → 200/503 readiness (Redis, Postgres, chiavi provider)
```

- **`POST /api/v1/trips` → 202 Accepted**: il lavoro è accettato, non completato. Header
  `Location` con l'URI del trip per il polling. Questo è il fix API più importante:
  allinea la semantica HTTP alla realtà del workflow (vedi `rest-patterns.md`: 202 per
  async processing).
- **`Idempotency-Key`** header obbligatorio su `POST /trips`: il frontend può ri-inviare
  per errore di rete; senza dedup una doppia submit = doppio costo LLM + doppia email
  (`docs/index.html:1097` non lo invia). Il lock `SET NX EX` esistente (`src/trip_store.py:80`)
  è già la primitiva per dedup per-id, ma l'idempotenza deve partire dal client.
- **`POST /api/v1/trips/{trip_id}/feedback`**: la tabella `feedback` esiste in
  `schema.sql:21-30` ma non c'è endpoint — il contratto dichiarato nel DB non è esposto.
- **`GET /api/v1/trips` (lista)**: oggi non c'è alcun consumatore. Quando servirà (es.
  dashboard dei founders), usare **cursor pagination** (`pagination.md`): la collection
  è su Postgres, cresce nel tempo, e il cursor evita COUNT costosi.
- **`/healthz` + `/readyz`**: contratti operativi richiesti da orchestratori/LB (FA-10).

### 8.4 Semantica degli stati (status machine nel contratto)

```
POST /trips → Trip(status=PENDING)
                │ claim() SET NX EX
                ▼
             RUNNING ──▶ DONE (email inviata + history salvata)
                │
                ▼
             ERROR (result = codice tipizzato, mai str(exc))
```

Lo stato è già modellato (`TripStatus` in `src/trip_store.py:10-14`) ma non è esposto
come contratto documentato. Il contratto deve dichiarare: transizioni legali, cosa
significa DONE/ERROR per il client, e che `result` è un **codice macchina** (es.
`EMAIL_SEND_FAILED`, `NO_RESOURCES`, `LLM_ERROR`) non la stringa dell'eccezione
(FA-6, `src/pipeline.py:83`).

### 8.5 Error model (RFC 7807 / Problem Details)

Oggi gli errori sono: FastAPI default (422 di pydantic, `detail` lista), `HTTPException`
404 con `detail` stringa (`src/routers/trips.py:45`), e 500 generici di Starlette.
Nessun formato unico, nessun `type` URI, nessun `request_id`. Il fix richiede:
1. Exception handler globali che mappino 400/404/422/429/500 in
   `application/problem+json` (FA-12).
2. `request_id` propagato (header di risposta + payload) per il debug (oggi manca a
   livello di richiesta; `src/pipeline.py` logga ma senza trace id).

**Catalogo errori target** (componenti `Problem` + `responses`):

| Status | `type` URI | Quando | Note |
|---|---|---|---|
| 400 | `/errors/validation-error` | campi non validi | `errors[]` con field-level detail |
| 401 | `/errors/unauthorized` | API key mancante/invalida | `WWW-Authenticate` |
| 403 | `/errors/forbidden` | autorizzazione fallita | |
| 404 | `/errors/trip-not-found` | trip assente **o scaduto** | oggi conflato, documentare la distinzione |
| 409 | `/errors/feedback-already-exists` | feedback già inviato per il trip | |
| 429 | `/errors/rate-limit-exceeded` | quota superata | header `Retry-After` + `X-RateLimit-*` |
| 500 | `/errors/internal-error` | errore inatteso | mai stack trace, mai `str(exc)` |
| 503 | `/errors/unavailable` | readiness fallita | header `Retry-After` |

### 8.6 Versioning e deprecation

Oggi non c'è strategia: la surface è implicitamente `/trips` = v1 senza documentazione.
Decisione raccomandata (allineata a `versioning.md`):
- **URI versioning** (`/api/v1/trips`): è la strategia più esplicita e facile da
  capire/debuggare per un'API piccola e pubblica.
- **Major versions only** (`v1`, `v2`), mai `v1.1` nell'URL.
- **Deprecation headers** quando una versione va in pensione: `Deprecation: true`,
  `Sunset: <RFC 8594>`, `Link: <url>; rel="successor-version"`.
- **Sunset** con 410 Gone + `type` documentato, mai disattivazione silenziosa.
- Il costo di partire oggi con `/api/v1` è quasi zero (2 endpoint); il costo di
  aggiungere versioning dopo è alto (FA-9).

### 8.7 Paginazione e filtri

Unico endpoint di collection previsto: `GET /api/v1/trips`. Raccomandazione:
- **Cursor pagination** su `created_at` (o `id`), con `limit` default 20 / max 100, e
  oggetto `pagination: {next_cursor, has_more}` — coerente con `pagination.md` e con
  dati che crescono su Postgres.
- **Filtri** come query param: `?email=...`, `?status=done` (per la dashboard). Applicare
  filtro prima della paginazione.
- Per la **collection feedback** sotto un trip, la stessa convenzione.

### 8.8 OpenAPI 3.1 come contratto formale

Oggi il contratto è quello che FastAPI genera a runtime (`/docs`, `/openapi.json`): corretto
ma **non formalizzato** — nessuno spec versionato nel repo, nessun lint, nessun test di
contratto con il frontend. Raccomandazioni:
- Mantenere FastAPI come **single source of truth runtime** (gli schemi pydantic
  generano già lo spec), ma:
  - aggiungere `tags`/`operationId`/`summary` espliciti su ogni endpoint;
  - aggiungere `components.responses` condivisi (Problem/404/422/429) e riferimenti
    `$ref` invece di `detail` inline;
  - aggiungere `examples` realistici per request/response (utile anche per il mock).
- **Validare** lo spec in CI (`npx @redocly/cli lint openapi.yaml`) e **mockare** durante
  lo sviluppo del frontend (`npx @stoplight/prism-cli mock openapi.yaml`) così il
  frontend si sviluppa contro il contratto, non contro il server.
- **Contract test** (`docs/index.html` ↔ spec): i campi che il frontend invia
  (`docs/index.html:1083-1094`) devono essere asseriti contro `TripCreateRequest`
  (oggi allineati, ma senza test si possono disallineare — FA-7/F5).

### 8.9 Findings API Design

| ID | Severità | Finding | Fix | Effort |
|----|---------|---------|-----|--------|
| AD-1 | 🔴 CRITICAL | `POST /trips` modella un lavoro asincrono ma risponde 200 come un create sincrono (`src/routers/trips.py:13-37`) | 202 Accepted + header `Location` per polling; documentare lo state machine | Moderato |
| AD-2 | 🔴 CRITICAL | Nessun error model unificato: 422/404/500 in formati diversi, `result=str(exc)` esposto (`src/pipeline.py:83`) | Handler globali → `application/problem+json` + catalogo `type` URI; `result` = codice tipizzato | Veloce |
| AD-3 | 🟠 HIGH | Nessun versioning né prefisso `/api/v1` (`src/routers/trips.py:10`) | URI versioning da subito + policy deprecation | Veloce |
| AD-4 | 🟠 HIGH | Nessuna idempotenza su POST: doppia submit = doppio costo + doppia email (`docs/index.html:1097`) | Header `Idempotency-Key` + dedup server-side | Moderato |
| AD-5 | 🟠 HIGH | Contratto non formalizzato: nessuno spec versionato, nessun lint/mock/contract test (`main.py:95`) | OpenAPI versionato in repo + redocly lint in CI + prism mock + contract test col frontend | Moderato |
| AD-6 | 🟡 MEDIUM | `GET /trips/{id}` confla 404 "assente" e "scaduto (TTL Redis)" (`src/trip_store.py:70`) | Distinguere nel problema model o restituire 410 per expiry | Veloce |
| AD-7 | 🟡 MEDIUM | Tabella `feedback` senza endpoint (`schema.sql:21-30`) | `POST /trips/{id}/feedback` + 409 su doppio invio | Veloce |
| AD-8 | 🟡 MEDIUM | Nessun `request_id`/trace id nei payload e nelle risposte | Middleware che genera/propaga request_id; log con trip_id | Veloce |
| AD-9 | 🟡 MEDIUM | Stato del trip documentato solo nel codice (`TripStatus`, `src/trip_store.py:10-14`) | State machine dichiarata nel contratto (transizioni, significato di DONE/ERROR per il client) | Veloce |
| AD-10 | 🔵 LOW | `POST /trips` senza `status_code=201`/`202` esplicito e senza `Location` | Semantica HTTP corretta + header di navigazione | Veloce |

---

## 9. Prossime sezioni previste

Questo documento è pensato per crescere. Possibili sezioni successive: approfondimento
database (fonte di verità, migrazioni, feedback), osservabilità (metriche/tracing/logging
strutturato), e topology di deploy (container, CI, proxy TLS).
