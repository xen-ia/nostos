# System Design Review — nostos

Review document for the nostos backend, conducted by specialized agents. Each
auditor owns a section named after their role. Findings are prioritized and
reference the code with `file:line` so fixes can be applied directly.

| Agente | Ambito | Stato |
|---|---|---|
| performance-engineer | Performance, scalabilità, concorrenza, deploy-readiness | ✅ completato — 2026-08-13 |
| security-auditor | Sicurezza applicativa, OWASP Top 10, protezione dati | ✅ completato — 2026-08-13 |
| test-automator | Copertura test, strategia di test, CI | ✅ completato — 2026-08-13 |
| backend-architect | Architettura servizi, workflow, consistenza, API contract, topology deploy | ✅ completato — 2026-08-13 |
| database-architect | (in arrivo) | ⏳ |

---


# `backend-architect` — Architettura servizi, workflow, consistenza, API contract, topology deploy

- **Data audit**: 2026-08-13
- **Scope**: modello di esecuzione dei workflow (`src/pipeline.py`, `src/routers/trips.py`), consistenza dei dati (`src/trip_store.py`, `src/database.py`, `schema.sql`), boundary dei componenti (`src/apis/`, `src/tools/`, `src/prompts/`), contratto API (`src/routers/trips.py`, `src/models.py`), configurazione e topology di deploy (`main.py`, `src/settings.py`, `.env.example`, assenza di Docker/CI)
- **Metodo**: reverse-engineering dell'architettura in diagramma C4 (componenti + dati), analisi del modello di consistenza e del flusso di esecuzione, valutazione dei pattern architetturali applicati (outbox, saga, coda job, CQRS) contro la scala del sistema, revisione della deployability
- **Verdetto**: **NON pronta per il deploy.** L'architettura è **corretta per un prototipo funzionante** ma **incompleta per la produzione**: il modello di esecuzione dei workflow è in-process e non durevole, la consistenza tra email e storico è fragile (dual-write senza outbox), la fonte di verità è ambigua tra Redis (TTL 24h) e Postgres, e la topology di deploy (container, CI, migrazioni, proxy) non esiste. I pattern di base sono però già posizionati bene (layering pulito, astrazione provider, lock anti-doppia) e il refactor richiesto è **evolutivo, non un rewrite**.
- **Intervento necessario**: introdurre coda job + worker dedicato (BA-1), pattern outbox per email/storico (BA-2), definire la fonte di verità (BA-3), rendere il workflow esplicito e componibile (BA-4), costruire la topology di deploy (BA-5). Da eseguire in coordinamento con PERF/SEC/TEST (cross-reference in ogni finding).

## Sommario finding

| ID | Severità | Titolo |
|---|---|---|
| BA-1 | 🔴 CRITICAL | Workflow a lunga durata eseguito in-process: nessun substrato di esecuzione (coda/worker) |
| BA-2 | 🔴 CRITICAL | Dual-write email/storico senza transactional outbox: consistenza non garantita |
| BA-3 | 🟠 HIGH | Fonte di verità ambigua: stato in Redis (TTL 24h) vs storico in Postgres, nessuna riconciliazione |
| BA-4 | 🟠 HIGH | Workflow implicito e monolitico in `TripOrchestrator.run`: nessuna fase componibile/repristinabile |
| BA-5 | 🟠 HIGH | Topology di deploy inesistente: no container/CI/proxy/migrazioni/secrets |
| BA-6 | 🟡 MEDIUM | Nessun contratto di osservabilità: log non strutturati, zero metriche/tracing, nessun health contract |
| BA-7 | 🟡 MEDIUM | Politica di degradazione incoerente tra le integrazioni esterne |
| BA-8 | 🟡 MEDIUM | API surface non versionata e contratto non formalizzato (OpenAPI di default) |
| BA-9 | 🟡 MEDIUM | Scope ambiguo: feature a metà integrate nel codice (`knowledge`, `feedback`, Qdrant) |
| BA-10 | 🟡 MEDIUM | Inizializzazione servizi fragile: nessun retry/backoff, pool senza parametri, nessun readiness gate |
| BA-11 | 🔵 LOW | Configurazione e secrets mescolati: default con credenziali, `.env.example` fuori sync |
| BA-12 | 🔵 LOW | Provider LLM scelto a runtime via CLI: decisione di deploy-time nel codice applicativo |

## Punti di forza (da preservare)

| # | Punto | Dove |
|---|---|---|
| ✅ | Layering pulito: `routers` (HTTP) → `pipeline` (orchestrazione) → `apis` (provider) / `tools` (capabilities) — le dipendenze puntano verso l'interno | struttura `src/` |
| ✅ | `LLMClient` come Protocol: l'orchestrazione dipende da un'astrazione, non da un provider concreto | `src/apis/llm.py:14-17` |
| ✅ | Boundary corretti con l'esterno: tutto l'I/O di rete è confinato in `src/apis/` e `src/tools/` | `src/apis/`, `src/tools/` |
| ✅ | Il lock `SET NX EX` è il mattone giusto per un futuro worker pool: l'astrazione del claim esiste già | `src/trip_store.py:80`, `src/pipeline.py:61` |
| ✅ | Modelli pydantic come contratto tra LLM e pipeline (`TripIntent`, `EmailContent`): extraction strutturata e validata | `src/models.py` |
| ✅ | Monolito singolo ben separato è la scelta giusta alla scala attuale: niente over-engineering di microservizi | — |
| ✅ | Degradazione controllata per SerpAPI (empty lists + `NoResourcesError`) dimostra consapevolezza dei fallimenti | `src/pipeline.py:150-169` |

---

## 🔴 CRITICAL

### BA-1. Workflow a lunga durata eseguito in-process: nessun substrato di esecuzione (coda/worker)

**Dove**: `src/routers/trips.py:35` (`background_tasks.add_task`), `src/pipeline.py:60-83` (`TripOrchestrator.run`), `src/trip_store.py:80` (lock)

Il sistema accoppia **due problemi diversi** nello stesso processo: servire richieste HTTP e **eseguire workflow a lunga durata** (LLM + SerpAPI + email, minuti di lavoro, costi reali). Architetturalmente manca il substrato di esecuzione:

- **Nessuna coda persistente**: il "job" esiste solo come hash Redis + lock; l'esecuzione vive nella memoria del worker HTTP.
- **Nessun worker dedicato**: il claim `SET NX EX` (buon mattone, vedi punti di forza) non ha un consumatore stabile a cui appoggiarsi.
- **Nessun redelivery**: un deploy/riavvio/crash perde il lavoro in volo; il trip resta `PENDING`/`RUNNING` per sempre (stessa radice di PERF-1).

**Fix architetturale**: separare il **request path** dal **workflow path**:
`POST /trips` → persistenza + enqueue (Redis Stream / ARQ) → **worker dedicato** (processo separato) che esegue la pipeline → stato aggiornato. Il worker usa il claim esistente come meccanismo di idempotenza/lease. Questo sblocca anche scale-out orizzontale e testabilità (TEST-4).

### BA-2. Dual-write email/storico senza transactional outbox: consistenza non garantita

**Dove**: `src/pipeline.py:75-78` (send_email → save_history), `src/database.py:28-51` (insert), `schema.sql` (`trip_history`)

Il sistema scrive su **due sistemi di record** (Resend + Postgres) senza un pattern di consistenza: se l'insert Postgres fallisce dopo l'invio, l'email esiste ma lo storico no (e viceversa su retry). È il classico **dual-write problem**, che richiede o un **transactional outbox** (persistere l'evento `email_to_send` nella stessa transazione dello stato, poi un dispatcher lo invia) o almeno un ordinamento che renda Postgres la fonte di verità prima dell'effetto esterno.

**Fix**: adottare l'**outbox pattern**: (1) la pipeline persiste `trip + intent + package + email_content` in Postgres **prima** di qualsiasi I/O esterno (una sola transazione); (2) un dispatcher legge l'outbox e invia via Resend; (3) `status=sent` solo dopo conferma. Il campo `package_json` di `trip_history` rende già possibile lo step (1) senza nuovi store. Allineato a PERF-4 (ordine) e verificabile con TEST-4.

---

## 🟠 HIGH

### BA-3. Fonte di verità ambigua: stato in Redis (TTL 24h) vs storico in Postgres, nessuna riconciliazione

**Dove**: `src/trip_store.py:70` (`expire` con TTL), `src/settings.py:21` (`redis_job_ttl_seconds=86400`), `src/database.py` (storico durevole), `src/routers/trips.py:40-45` (`GET /trips/{id}`)

Due viste dello stesso concetto "trip" senza relazione:
- **Redis**: stato operativo (PENDING/RUNNING/DONE/ERROR) con TTL 24h — dopo 24h `GET /trips/{id}` risponde **404** anche se l'email è stata inviata e registrata;
- **Postgres**: storia durevole delle email inviate, senza stato operativo né `trip_id` ricollegabile allo stato corrente.

Architetturalmente manca la **definizione esplicita del system of record**: oggi il sistema *appare* consistente solo perché il TTL è lungo abbastanza per il caso d'uso demo. In produzione un utente che richiede il proprio trip dopo 24h riceverebbe un 404 con dati presenti in DB — UX e operatività incoerenti.

**Fix**: Postgres diventa la fonte di verità del trip (stato incluso: aggiungere colonna `status` a `trip_history`, oppure tabella `trips` con stato + join allo storico); Redis resta **cache/indicizzatore transitorio** (TTL corto) o viene eliminato a favore della coda job (BA-1). La risposta 404 deve riflettere una vera assenza, non l'expiry di una cache.

### BA-4. Workflow implicito e monolitico in `TripOrchestrator.run`: nessuna fase componibile/repristinabile

**Dove**: `src/pipeline.py:60-83` (`run`), `:134-192` (metodi `_*` privati), `src/trip_store.py:10-14` (stati)

Il workflow è un **monolite sequenziale** con stati dichiarati (`PENDING/RUNNING/DONE/ERROR`) ma **nessuna macchina a stati reale**: lo stato cambia solo a inizio (`RUNNING`) e a fine (`DONE`/`ERROR`). Conseguenze architetturali:
- impossibile riprendere da una fase intermedia (es. "email inviata, storico no") senza ri-eseguire tutto;
- impossibile applicare politiche per-fase (retry solo su SerpAPI, timeout solo su LLM, backoff solo su email);
- l'osservabilità per-step si riduce ai singoli `_timed` log.

**Fix**: modellare il workflow come **fasi esplicite e componibili** (es. `extract_intent → gather_resources → compose → dispatch → record`), ognuna con: stato persistito, retry policy propria, idempotenza. Questo è il prerequisito per BA-1/BA-2 (le fasi diventano gli step consumati dal worker/outbox) e rende la pipeline testabile fase-per-fase (TEST-4).

### BA-5. Topology di deploy inesistente: no container/CI/proxy/migrazioni/secrets

**Dove**: repo (nessun `Dockerfile`, `docker-compose`, CI), `schema.sql` (applicato a mano, contiene anche una SELECT di ispezione `:33-64`), `main.py:26-50` (config via CLI), `.env.example` (6 righe, fuori sync con `src/settings.py`)

L'architettura non è deployabile senza decisioni *ad hoc* al momento del go-live: mancano containerizzazione, orchestrazione, reverse proxy/TLS, pipeline CI/CD, migrazioni versionate, gestione secrets. La strategia di config è divisa tra CLI (provider, timeout), `.env` (secrets) e default in `settings.py` — tre posti diversi per la stessa superficie di configurazione.

**Fix**: definire la topology target (es. Dockerfile multi-stage non-root + compose per app/redis/postgres + proxy TLS; CI su GitHub Actions — visto che il frontend è già su GitHub Pages); migrazioni con tooling semplice (es. `alembic` o file SQL versionati `001_...sql`); unificare la configurazione su env vars (BA-12). La checklist deploy già presente nella sezione performance-engineer elenca i componenti mancanti.

---

## 🟡 MEDIUM

### BA-6. Nessun contratto di osservabilità: log non strutturati, zero metriche/tracing, nessun health contract

**Dove**: `main.py:14-19` (logging Rich), assenza di `/metrics` e `/healthz`, `src/pipeline.py:70` (PII nei log)

Nessun contratto tra l'applicazione e l'infrastruttura operativa: log in formato proprietario, zero metriche esportabili, zero tracing, nessun endpoint di health per gli orchestratori (stessa radice di PERF-12/PERF-6). Un'architettura di produzione richiede che l'applicazione **esponga** il proprio stato in modo standard.

**Fix**: JSON logging strutturato con `trip_id`; `/metrics` Prometheus (RED: rate/errors/duration per fase pipeline); endpoint `/healthz` (liveness) + `/readyz` (Redis, Postgres, chiavi provider presenti); opzionale OpenTelemetry per tracing una volta introdotti coda+worker (BA-1).

### BA-7. Politica di degradazione incoerente tra le integrazioni esterne

**Dove**: `src/tools/flights.py:56-59`, `src/tools/maps.py:37-40`, `src/tools/places.py:56-59` (fail-open → lista vuota), `src/pipeline.py:81-83` (fail-closed → ERROR), `src/apis/email.py:85-88` (fail-closed)

Le tre integrazioni hanno politiche di fallimento diverse e **non documentate**:
- **SerpAPI**: fail-open silenzioso (lista vuota, l'email degrada senza allarme);
- **LLM**: fail-closed (trip intero in ERROR);
- **Email**: fail-closed (ma dopo che i costi sono già bruciati).

Architetturalmente serve una **policy esplicita per dipendenza** (fail-open per dati di arricchimento, fail-closed per l'effetto contrattuale) con conseguenze definite e metriche (quanto spesso degrada?).

**Fix**: definire una matrice di degradazione per integrazione (che cosa succede, che stato assume il trip, che metrica emette); documentarla in un ADR. Con BA-4 (fasi esplicite) la policy diventa applicabile per-fase.

### BA-8. API surface non versionata e contratto non formalizzato (OpenAPI di default)

**Dove**: `src/routers/trips.py:10` (prefix `/trips` senza versione), `main.py:95` (FastAPI di default), `docs/index.html` (consumer), `src/models.py` (schemi)

L'API è esposta senza **strategia di versioning** esplicita (implicitamente v1) e senza contratto formalizzato oltre al default FastAPI: nessun OpenAPI customizzato, nessuna politica di deprecazione, nessun contratto testato con il frontend (TEST-9). Alla scala attuale (2 endpoint) il rischio è basso, ma il costo di introdurre versioning dopo è alto.

**Fix**: decidere ora la strategia (URL `/v1/trips` vs header) e registrarla in un ADR; generare/docs OpenAPI come contratto; contract test con `docs/index.html` (TEST-9). Con l'introduzione dell'auth (SEC-1) il contratto andrà esteso coerentemente.

### BA-9. Scope ambiguo: feature a metà integrate nel codice (`knowledge`, `feedback`, Qdrant)

**Dove**: `src/knowledge.py` (vuoto), `src/settings.py:27` (`qdrant_url` inutilizzato), `schema.sql:21-30` (tabella `feedback` senza endpoint), `src/templates/trip_template.*` (inutilizzati)

Componenti presenti nel codicebase ma **non collegati al flusso**: il perimetro reale del sistema (cosa fa oggi vs cosa doveva fare) è ambiguo. Questo è un problema architetturale di **scope management**: chi legge il codice non sa se `knowledge`/RAG è un requisito attivo o abbandonato.

**Fix**: decidere e dichiarare lo scope: se RAG/feedback non sono nel go-live, **rimuovere o marcare esplicitamente** (directory `experimental/`, ADR); evitare che `schema.sql` crei tabelle senza consumatore (stessa indicazione di SEC/database-architect quando arriva).

### BA-10. Inizializzazione servizi fragile: nessun retry/backoff, pool senza parametri, nessun readiness gate

**Dove**: `main.py:86-87` (`create_pool`/`from_url` senza retry né parametri), `src/settings.py:24` (URL), `main.py:95` (nessun readiness)

Il bootstrap collega Redis e Postgres **una volta** senza gestione dei fallimenti: se un servizio è temporaneamente giù al boot, l'app muore (accettabile solo con restart policy dell'orchestratore — che non esiste, BA-5). Non c'è nessun gate di readiness prima di accettare traffico.

**Fix**: retry con backoff all'avvio; parametri pool (`min_size`, `max_size`, `command_timeout` — vedi PERF-13); `/readyz` che riflette lo stato delle dipendenze (BA-6); in container, dipendenze gestite dall'orchestratore con healthcheck.

---

## 🔵 LOW

- **BA-11. Configurazione e secrets mescolati**: `src/settings.py` contiene default con credenziali (`postgres:postgres`), `.env.example` non allineato ai campi di `Settings`, nessun uso di `SecretStr` — la configurazione è distribuita tra CLI/`.env`/default (stessa radice di SEC-6). **Fix**: env vars come unica fonte, `SecretStr` per i secrets, `.env.example` generato/sincronizzato.
- **BA-12. Provider LLM scelto a runtime via CLI**: `main.py:26-50` e `src/dependencies.py:24-45` selezionano il provider da un flag `--claude|--gpt|--ollama` — una decisione di **deploy-time** (quale provider gira in quell'ambiente) codificata come **runtime choice** nel processo. **Fix**: `NOSTOS_LLM_PROVIDER` env var; il CLI resta solo come convenienza dev (in sinergia con PERF-7).

---

## Piano di priorità

**Fase 1 — Fondamenta di consistenza ed esecuzione (~2–3 giorni):**
1. BA-2: persistenza prima dell'effetto esterno (outbox semplificato: insert completo in `trip_history` → poi invio → poi `sent`) — sblocca PERF-4 e TEST-4
2. BA-4: fasi esplicite del workflow (stato per-fase, retry policy per-fase) — prerequisito di BA-1
3. BA-1: worker dedicato con coda Redis (riusa il claim `SET NX EX` esistente) — risolve la durabilità di PERF-1

**Fase 2 — System of record e operabilità (~1–2 giorni):**
4. BA-3: Postgres come fonte di verità (stato incluso), Redis come cache/coda
5. BA-6: JSON logging + `/healthz`/`/readyz` + `/metrics`
6. BA-7: matrice di degradazione per integrazione + ADR
7. BA-8: versioning API + OpenAPI come contratto

**Fase 3 — Topology di deploy (~2–3 giorni):**
8. BA-5: Dockerfile + compose + proxy TLS + CI (GitHub Actions)
9. BA-10: bootstrap con retry/backoff + readiness gate
10. BA-11/BA-12: unificazione config su env vars, `.env.example` sincronizzato
11. BA-9: decisione di scope su knowledge/feedback/Qdrant + ADR

---

# `performance-engineer` — Performance, scalabilità, concorrenza, deploy-readiness

- **Data audit**: 2026-08-13
- **Scope**: intero backend — `main.py`, `src/` (pipeline, trip_store, database, apis, tools, prompts, routers, settings), `schema.sql`, `pyproject.toml`, `.env.example`, template email
- **Metodo**: lettura completa del codice; analisi performance su: latenza dei percorsi critici (LLM/SerpAPI/email), throughput e concorrenza del flusso background, utilizzo di risorse (pool di connessioni, thread pool, memoria), scalabilità orizzontale, affidabilità del flusso (ritentivi, durata job, timeouts) in quanto impatta direttamente latency e throughput
- **Verdetto**: **NON pronta per il deploy in produzione.** L'architettura di base è buona e modulare, ma ci sono **5 problemi bloccanti** (PERF-1–PERF-5) che in produzione causano email duplicate, task persi, costi bruciati e dati non registrati; **l'infrastruttura di deploy è completamente assente** (no Dockerfile, compose, CI, healthcheck, migrazioni, monitoring).
- **Intervento necessario**: bugfix mirati (PERF-3, PERF-14, PERF-8, PERF-11) + refactor architetturale circoscritto (PERF-1, PERF-2, PERF-4, PERF-7). Non serve un rewrite.

## Sommario finding

| ID | Severità | Titolo |
|---|---|---|
| PERF-1 | 🔴 CRITICAL | Workflow in-process non durevole (`BackgroundTasks`) → task persi, zero scalabilità orizzontale |
| PERF-2 | 🔴 CRITICAL | Lock TTL (300s) < durata reale della pipeline → email duplicate |
| PERF-3 | 🔴 CRITICAL | Nessun timeout sulle chiamate LLM → job bloccati indefinitamente |
| PERF-4 | 🔴 CRITICAL | Ordine sbagliato email→storico + zero retry → dati persi |
| PERF-5 | 🔴 CRITICAL | Nessuna autenticazione né rate limiting → API aperta e costosa |
| PERF-6 | 🟠 HIGH | Startup fragile e nessun healthcheck |
| PERF-7 | 🟠 HIGH | Entrypoint fragile (`argparse` a livello di modulo, `reload=True` di default) |
| PERF-8 | 🟠 HIGH | Discrepanza AGENTS.md ↔ codice su OllamaClient (think/num_ctx) |
| PERF-9 | 🟠 HIGH | Feature a metà: `feedback`, `knowledge`, Qdrant |
| PERF-10 | 🟡 MEDIUM | Error handling LLM fragile, senza retry |
| PERF-11 | 🟡 MEDIUM | Scritture Redis non atomiche e tipi fragili |
| PERF-12 | 🟡 MEDIUM | Osservabilità assente: niente metriche, log non strutturati, PII nei log |
| PERF-13 | 🟡 MEDIUM | Sizing e timeout delle connessioni (PG, Redis) |
| PERF-14 | 🟡 MEDIUM | Validazione input insufficiente (email, date, lunghezza) |
| PERF-15 | 🟡 MEDIUM | CORS di produzione non gestito + endpoint feedback mancante |
| PERF-16 | 🔵 LOW | Help flag in italiano, typo commenti, client ricostruiti, ecc. |

## Punti di forza (da preservare)

| # | Punto | Dove |
|---|---|---|
| ✅ | Separazione pulita `apis/` (provider) vs `tools/` (capabilities) vs `routers/` | struttura `src/` |
| ✅ | `LLMClient` come Protocol → provider swappabili senza toccare la pipeline | `src/apis/llm.py` |
| ✅ | Estrazione strutturata via tool-call vincolata a schemi pydantic (niente parsing free-form) | `src/apis/llm.py`, `src/tools/__init__.py` |
| ✅ | `asyncio.gather(..., return_exceptions=True)` per le 3 ricerche SerpAPI (parallelismo con degradazione) | `src/pipeline.py:144` |
| ✅ | `NoResourcesError` evita email vuote con zero risorse | `src/pipeline.py:158` |
| ✅ | Escape HTML su tutte le variabili LLM nel template email (anti-XSS) | `src/apis/email.py:49-71` |
| ✅ | Lock `SET NX EX` contro doppia esecuzione (concetto giusto, TTL sbagliato → PERF-2) | `src/trip_store.py:80` |
| ✅ | Risposta HTTP immediata, flusso pesante in background | `src/routers/trips.py:35` |
| ✅ | `.env` gitignored, `uv.lock` committato (riproducibilità) | `.gitignore`, repo |

---

## 🔴 CRITICAL — bloccanti per il deploy

### PERF-1. Workflow in-process non durevole → task persi, trip bloccati per sempre

**Dove**: `src/routers/trips.py:35` — `background_tasks.add_task(orchestrator.run)`

Il flusso gira in `fastapi.BackgroundTasks`, che vive **solo nella memoria del worker** che ha ricevuto la richiesta:

- **Worker che muore o viene riavviato** (deploy, OOM, crash) → il task sparisce, il trip resta `PENDING`/`RUNNING` per sempre. Nessun redelivery.
- **Allo shutdown** (il lifespan chiude Redis/PG dopo il `yield` in `main.py:89-92`) i task in-flight vengono interrotti mentre usano pool già chiusi → trip bloccato in `RUNNING` + eccezioni.
- **Impatto performance/scalabilità**: i task a lunga durata (LLM + SerpAPI + email) restano legati al worker HTTP: impediscono lo scale-out (`--workers N` non aiuta, anzi moltiplica il rischio di task orfani) e con `reload=True` un riavvio del watcher perde tutto il lavoro in volo.

**Fix**: coda di job persistente (minimo: **Redis Stream + worker dedicato** con claim/redelivery; oppure ARQ/Celery/RQ) con lo stato dei trip come fonte di verità nel DB, non solo in memoria del processo. Pattern target: `POST /trips` → insert DB + enqueue → worker esegue → aggiorna stato. Il claim `SET NX EX` esistente è già un buon mattone per un worker pool — basta spostare `orchestrator.run` fuori dal processo HTTP.

### PERF-2. Lock TTL (300s) < durata reale della pipeline → email duplicate

**Dove**: `src/pipeline.py:32` — `LOCK_TTL_SECONDS = 300`; claim in `src/trip_store.py:80`

La pipeline può durare molto più di 300s:

- SerpAPI: 3 ricerche parallele fino a 60s ciascuna (~60s totali)
- LLM: **senza timeout** (vedi PERF-3) → può durare indefinitamente
- Email: fino a 60s

Se il lock scade mentre il primo run è ancora vivo, un retry/riavvio del worker riesegue il trip → **email doppia al cliente** + doppio costo LLM/SerpAPI. È il guasto che il lock doveva prevenire, ma con TTL troppo corto e nessun rinnovo; inoltre il lock **non viene mai rilasciato né rinnovato** a fine run.

**Fix**: lock con **lease rinnovata** (heartbeat ogni ~30–60s) o TTL ≥ budget massimo della pipeline + **timeout su tutte le chiamate** (PERF-3). Rilascio esplicito del lock a fine pipeline.

### PERF-3. Nessun timeout sulle chiamate LLM

**Dove**: `src/apis/llm.py:27` (`messages.create`), `:46` (`responses.create`), `:66` (`chat`)

Nessun timeout: un hang del provider (rete, provider down) blocca il background task per sempre e, combinato con PERF-2, produce email duplicate. **Impatto performance**: un job in hang consuma una slot di concorrenza del worker senza limite superiore, degradando il throughput dell'intero processo.

**Fix**: timeout espliciti — Anthropic `timeout=`, OpenAI `timeout=`, Ollama `timeout=` (o `asyncio.wait_for`), con errori tipizzati e retry transitorio (vedi PERF-10).

### PERF-4. Ordine sbagliato: email inviata PRIMA dello storico + zero retry

**Dove**: `src/pipeline.py:75-78` (send_email → save_history); `src/database.py:40-41` (`date.fromisoformat`)

- Se il salvataggio Postgres fallisce (data invalida, PG giù, pool chiuso), **l'email è partita ma lo storico è perso** → status `ERROR` con email consegnata. Per un'agenzia che deve dare seguito alla conversazione è inaccettabile.
- Il `date.fromisoformat` esplode **solo a fine flusso**, dopo aver bruciato 2 chiamate LLM + 3 ricerche SerpAPI (i costi dominanti della pipeline), perché l'API accetta `start_date: Optional[str]` senza validazione (vedi PERF-14).
- Se Resend dà un errore transitorio o timeout → trip `ERROR` senza retry; e se il timeout è scaduto ma Resend aveva accettato, un retry manuale duplica l'email (nessuna idempotency).

**Fix**: (1) persistire **intent + package + contenuto nel DB prima dell'invio** (fonte di verità), (2) poi inviare, (3) poi marcare `sent`. Retry con backoff esponenziale su errori transitori, idempotenza sul lato email (reference id dedup lato Resend). Validare le date all'ingresso (PERF-14).

### PERF-5. Nessuna autenticazione né rate limiting → API aperta e costosa

**Dove**: `src/routers/trips.py` — nessuna auth, nessun rate limit

Ogni `POST /trips` brucia **2 chiamate LLM + 3 ricerche SerpAPI + 1 email Resend** (tutti servizi a pagamento). Un bot può prosciugare il budget in minuti e farsi inviare email verso indirizzi arbitrari. **Impatto performance**: senza rate limiting, un picco di richieste bot satura i pool di connessione e le quote dei provider, degradando il servizio per gli utenti reali.

**Fix minimo per andare live**: rate limiting per IP + per email (slowapi o limiti Redis a sliding window), validazione email (`EmailStr`), cap su `free_text` e `travelers_count`. Se il frontend è pubblico (GitHub Pages), aggiungere token d'accesso condiviso o honeypot/CAPTCHA.

---

## 🟠 HIGH — da sistemare prima del go-live

### PERF-6. Startup fragile e nessun healthcheck

**Dove**: `main.py:86-87`

Se Redis o Postgres sono giù al boot, l'app fallisce senza backoff/retry (accettabile solo con restart policy dell'orchestratore). In più **non esiste `/healthz`** (liveness) né `/readyz` (Redis+PG up, chiavi API presenti) → orchestratori e load balancer non sanno se il servizio è pronto e non possono instradare traffico in modo affidabile.

**Fix**: endpoint di health/readiness + retry con backoff alla creazione dei pool.

### PERF-7. Entrypoint fragile e non adatto alla produzione

**Dove**: `main.py:26-50`, `src/settings.py:17`

- `argparse` a livello di modulo: il parsing gira **due volte** (l'import di `main` da parte di `uvicorn.run("main:app", ...)` ri-esegue il top-level). L'app funziona solo lanciata come `python main.py`; con `uvicorn main:app --workers 4` (come farebbe qualsiasi orchestrazione) argparse scoppia su `--workers`.
- `reload: bool = True` **di default**: in produzione un reload watcher attivo = deploy non deterministico + riavvii che perdono i job in volo (PERF-1).
- `host: "127.0.0.1"` di default non serve dietro un container/proxy.
- Provider LLM scelto via **flag CLI** → scomodo in container: spostare a `NOSTOS_LLM_PROVIDER` (env var).

**Fix**: parsing in `run()` / `if __name__ == "__main__"`, `reload=False` in prod, provider via env.

### PERF-8. Discrepanza AGENTS.md ↔ codice su OllamaClient

**Dove**: `src/apis/llm.py:64-82` vs `AGENTS.md`

AGENTS.md dichiara: *"OllamaClient sends `think=False` + `num_ctx`"* — ma il codice non li invia. Con un modello Qwen3 in thinking mode il JSON extraction si rompe proprio come la doc dice di prevenire. **Impatto performance**: un modello in thinking mode genera token extra e ritenta parsing, moltiplicando latenza e costi oltre al rischio di fallimento. O il codice è stato semplificato e la doc non aggiornata, o manca un fix reale. **Da risolvere prima di usare Ollama in produzione.**

### PERF-9. Feature a metà: `feedback`, `knowledge`, Qdrant

**Dove**: `schema.sql:21-30` (tabella `feedback` senza endpoint), `src/knowledge.py` (vuoto), `src/knowledge/*.md` (mai caricati), `src/settings.py:27` (`qdrant_url` morto)

Non blocca il deploy, ma va deciso: **rimuovere o completare**. Inoltre `schema.sql:33-64` contiene una **SELECT di ispezione** eseguita come parte dello script — da togliere.

---

## 🟡 MEDIUM — raccomandati prima del deploy

### PERF-10. Error handling LLM fragile, senza retry

**Dove**: `src/apis/llm.py:35` (`next(... if b.type == "tool_use")`), `:54`, `:82`

Se il modello non produce tool_use (refusal, safety, formato), `StopIteration` → trip in `ERROR` con messaggio incomprensibile. Nessun retry su rate-limit/5xx, nessun fallback. **Impatto performance**: su 429/5xx transitori l'intera pipeline (già costosa) va sprecata senza possibilità di recupero.

**Fix**: helper comune con retry (1–2 tentativi, backoff), errore tipizzato, log strutturato.

### PERF-11. Scritture Redis non atomiche e tipi fragili

**Dove**: `src/trip_store.py:68-70` (`hset` + `expire` in due round-trip), `:100` (`str(...) == "True"`)

Se il processo muore in mezzo, trip senza TTL. `flexible_dates` salvato come `str(bool)` e riletto con `== "True"` — fragile.

**Fix**: pipeline Lua o un solo campo JSON (`data`) + `SET EX`.

### PERF-12. Osservabilità: niente metriche, log non strutturati, PII nei log

**Dove**: `main.py:18` (RichHandler `markup=True`), `src/pipeline.py:70` (`intent.model_dump()` in chiaro), `src/apis/serpapi.py:19` (tutti i `params`)

- Nessuna metrica Prometheus (trip per status, latenze LLM/SerpAPI/email), nessun tracing → impossibile capire dove va il tempo nei SLO.
- `markup=True` → **log injection**: valori utente (destination, free_text) contenenti `[red]`/tag Rich corrompono i log.
- PII (email, free_text) nei log non strutturati → GDPR.

**Fix minimo**: JSON logs con campo `trip_id`, `markup=False`, `GET /metrics` con contatori e istogrammi di latenza per LLM/SerpAPI/email.

### PERF-13. Sizing e timeout delle connessioni

**Dove**: `main.py:87` (`asyncpg.create_pool` senza `min_size/max_size/command_timeout`), Redis senza `socket_connect_timeout`/`health_check_interval`, `src/apis/serpapi.py:21` (nuovo `Client` a ogni chiamata)

Default 10 conn PG: sotto picco di task in parallelo si satura (ogni job usa 1 conn per `save_trip_history`) → code su `asyncpg` che allungano la latenza percepita. Possibile hang su Redis.

**Fix**: `max_size` adeguato al numero di worker × job concorrenti + `command_timeout`, `health_check_interval` Redis, client SerpAPI condiviso (oggi ricreato a ogni ricerca).

### PERF-14. Validazione input insufficiente

**Dove**: `src/trip_store.py:17-27` (`TripCreateRequest`)

- `email: str` → dovrebbe essere `EmailStr` (oggi email invalida = costo bruciato + errore oscuro da Resend).
- `start_date`/`end_date`: nessun check di formato/ordinamento (`end >= start`) → il fallimento arriva a fine pipeline (PERF-4), dopo aver bruciato il costo dominante della pipeline.
- `free_text` senza limite di lunghezza (payload LLM crescenti → latenza e costo più alti).
- `travelers_count` ha `ge=1` ma manca tetto alto.

### PERF-15. CORS di produzione non gestito + endpoint feedback mancante

**Dove**: `main.py:97-103`, `schema.sql:21-30`

Il frontend è servito da GitHub Pages (`xen-ia.github.io`): `NOSTOS_ALLOWED_ORIGINS` dovrà includere l'URL reale; il default attuale (`localhost:5500`) bloccherebbe tutto in produzione. La tabella `feedback` non ha nessun endpoint.

---

## 🔵 LOW / polish

- `main.py:31-33` — help dei flag in italiano dentro un codebase inglese.
- `src/settings.py:53` — typo commento ("Last recently use cache function").
- `src/dependencies.py:24` — `get_llm_client` ricostruisce il client a ogni request (trascurabile in termini di costo, ma facile da rendere singleton).
- `src/apis/email.py:76` — `resend.api_key` globale condivisa tra istanze (accettabile).
- `src/settings.py:10` — `extra="ignore"`: un typo in `.env` viene ignorato in silenzio → meglio `extra="forbid"` o warning.
- `src/trip_store.py` — il lock non viene mai rilasciato a fine run (muore solo con TTL).

---

## Checklist deploy — infrastruttura completamente mancante

| Componente | Stato |
|---|---|
| Dockerfile (multi-stage, non-root, HEALTHCHECK) | ❌ non esiste |
| docker-compose (app + redis + postgres) | ❌ non esiste |
| Reverse proxy + TLS (nginx/Caddy/Traefik) | ❌ non esiste |
| Migrazioni DB versionate (oggi `schema.sql` a mano) | ❌ |
| CI/CD (test, lint, typecheck, build, deploy) | ❌ (e non esistono test né linter) |
| Health/readiness endpoint | ❌ |
| Metriche + log centralizzati + alerting | ❌ |
| Backup Postgres | ❌ |
| Secrets management (oggi solo `.env` locale) | ❌ |
| Test: unit, integrazione, E2E | ❌ (nessun pytest/ruff/mypy/CI, confermato da AGENTS.md) |

---

## Piano di priorità

**Fase 1 — Bugfix urgenti (~mezza giornata):**
1. PERF-3: timeout su tutte le chiamate LLM
2. PERF-14: validazione input (EmailStr, date, length)
3. PERF-8: riallineare OllamaClient alla doc (think=False + num_ctx)
4. PERF-11: scritture Redis atomiche
5. PERF-12: `markup=False` nei log + ridurre PII

**Fase 2 — Refactor architetturale (2–3 giorni):**
6. PERF-1: spostare il flusso da `BackgroundTasks` a coda Redis + worker (si riusa il lock `SET NX EX` esistente)
7. PERF-2: lock con lease rinnovata + release esplicita
8. PERF-4: invertire l'ordine (storico prima dell'invio) + retry con backoff + idempotenza email
9. PERF-5: rate limiting + minimo di auth

**Fase 3 — Infrastruttura deploy (2–3 giorni):**
10. PERF-6: `/healthz` + `/readyz`
11. PERF-7: entrypoint pulito, `reload=False` in prod, provider via env
12. Dockerfile + compose + proxy TLS
13. CI con almeno lint + typecheck + test minimi sul flusso (pipeline con mock)

---

# `security-auditor` — Sicurezza applicativa, OWASP Top 10, protezione dati

- **Data audit**: 2026-08-13
- **Scope**: superficie API (`src/routers/trips.py`), input validation (`src/trip_store.py`), pipeline e handling errori (`src/pipeline.py`), provider esterni e secrets (`src/settings.py`, `src/apis/`, `.env.example`), logging (`main.py`), schema dati (`schema.sql`)
- **Metodo**: threat modeling sugli endpoint esposti, revisione OWASP Top 10 (2021), analisi input injection / log injection / information disclosure / secrets management / trasporto, verifica di `.gitignore` e dipendenze
- **Verdetto**: **NON pronta per il deploy.** Nessuna autenticazione né rate limiting su un'API che brucia risorse a pagamento (LLM + SerpAPI + Resend) per ogni chiamata; input utente fluisce in prompt LLM e nei log senza controlli adeguati; exposure di dettagli interni via API. Le difese esistenti (escape HTML nelle email, CORS ristretto, `.env` gitignored) sono corrette ma insufficienti da sole.
- **Intervento necessario**: bugfix critici (SEC-1, SEC-2, SEC-3) + hardening (SEC-4, SEC-5, SEC-6) + procedure (SEC-8, SEC-9). Da eseguire in parallelo ai fix strutturali del performance-engineer (PERF-5, PERF-14).

## Sommario finding

| ID | Severità | Titolo |
|---|---|---|
| SEC-1 | 🔴 CRITICAL | Nessuna autenticazione né autorizzazione: tutti gli endpoint aperti |
| SEC-2 | 🔴 CRITICAL | Nessun rate limiting → cost-DoS e abuso del budget |
| SEC-3 | 🟠 HIGH | Nessuna validazione email → spam relay verso indirizzi arbitrari |
| SEC-4 | 🟠 HIGH | Prompt injection via `free_text` → link malevoli/phishing nelle email |
| SEC-5 | 🟠 HIGH | Log injection (Rich markup) + PII nei log |
| SEC-6 | 🟠 HIGH | Credenziali di default (`postgres:postgres`) e secrets management assente |
| SEC-7 | 🟡 MEDIUM | Information disclosure: `result=str(exc)` esposto via API |
| SEC-8 | 🟡 MEDIUM | Nessuno scanning dipendenze / CI → CVE non gestiti |
| SEC-9 | 🟡 MEDIUM | Logging/monitoring insufficiente (A09) + security headers assenti |
| SEC-10 | 🟡 MEDIUM | Validazione input incompleta: date, lunghezze, payload |
| SEC-11 | 🟡 MEDIUM | CORS da riconfigurare in produzione + `allow_headers=["*"]` |
| SEC-12 | 🟡 MEDIUM | Nessuna enforcement TLS a livello applicativo |
| SEC-13 | 🔵 LOW | Errori HTTP verbose (default FastAPI) |
| SEC-14 | 🔵 LOW | IDOR mitigato solo dall'imprevedibilità degli UUID |

## Punti di forza (da preservare)

| # | Punto | Dove |
|---|---|---|
| ✅ | Escape HTML su tutte le variabili LLM nel template email (anti-XSS) | `src/apis/email.py:49-71` |
| ✅ | `.env` gitignored, nessun secret committato | `.gitignore` |
| ✅ | CORS ristretto di default (`localhost:5500`), `allow_credentials=False` | `main.py:97-103` |
| ✅ | Tool-call vincolato a schema pydantic: l'output LLM è strutturato, niente markdown/HTML libero dal modello | `src/apis/llm.py` |
| ✅ | `Literal` tipizzati su `travelers_type` e `budget_range` (whitelist) | `src/trip_store.py:24-25` |
| ✅ | Nessun file caricato da utenti, nessuna query SQL costruita con input utente (parametri `$1..$14`) | `src/database.py` |
| ✅ | Email senza allegati e senza header utente (subject/from controllati dal server) | `src/apis/email.py` |

---

## 🔴 CRITICAL

### SEC-1. Nessuna autenticazione né autorizzazione: tutti gli endpoint aperti

**Dove**: `src/routers/trips.py:13-45` — `POST /trips` e `GET /trips/{trip_id}` senza alcun middleware di auth

Qualunque utente (o bot) può:
- **creare trip** a volontà, facendo bruciare LLM + SerpAPI + Resend (costi per l'azienda);
- **leggere i dettagli di un trip**, incluse `email` e `free_text` (PII del richiedente), se conosce il `trip_id`.

Il `trip_id` è un UUIDv4 (imprevedibile, quindi l'enumerazione è difficile — vedi SEC-14), ma il principio è violato: l'accesso ai dati non è legato a chi li ha creati.

**Fix**: introdurre un livello minimo di autenticazione (API key per il frontend pubblico, meglio: sessione/token per il cliente), e autorizzazione su `GET /trips/{id}` (solo il creatore del trip o un admin).

### SEC-2. Nessun rate limiting → cost-DoS e abuso del budget

**Dove**: `src/routers/trips.py` — nessun limite; `main.py` — nessun middleware

Ogni `POST /trips` costa **2 chiamate LLM + fino a 3 ricerche SerpAPI + 1 email Resend**. Senza rate limiting, un singolo attaccante può prosciugare il budget giornaliero (o la quota SerpAPI) in pochi minuti, rendendo il servizio inutilizzabile per gli utenti reali (**cost-DoS**).

**Fix**: rate limiting per IP e per email con finestra a sliding window (es. `slowapi` o Redis); soglie basse su `POST /trips` (es. 5–10/ora/IP); alerting quando si avvicina la quota di un provider.

---

## 🟠 HIGH

### SEC-3. Nessuna validazione email → spam relay verso indirizzi arbitrari

**Dove**: `src/trip_store.py:18` — `email: str` (nessun vincolo)

L'API accetta qualunque stringa nel campo `email`. Conseguenze:
- un attaccante può far inviare email Nostos (branded, da `email_from_address`) verso **indirizzi arbitrari**, usando il servizio come relay per spam/phishing con mittente legittimo;
- email malformate → errore oscuro da Resend dopo aver bruciato i costi di pipeline.

**Fix**: `email: EmailStr` (pydantic) + whitelist di dominio se il pubblico è noto; `from` di invio separato e fisso (già il caso). Valutare CAPTCHA/honeypot sul frontend pubblico.

### SEC-4. Prompt injection via `free_text` → link malevoli/phishing nelle email

**Dove**: `src/prompts/__init__.py:11-22` (`free_text` interpolato nel prompt intent), `src/pipeline.py:178-191` (LLM compone le risorse dell'email)

`free_text` è testo utente iniettato direttamente nel prompt. Il sistema prompt impone "solo risorse reali fornite", ma un prompt injection può:
- far scegliere/comporre al modello **link non reali** nelle card dell'email (il modello inventa URL di phishing/host malevoli);
- estrarre contenuto del system prompt o della conversazione (information leak del brand/prompt engineering).

L'escape HTML (punti di forza) previene lo **scripting** ma **non** il **phishing**: un link `https://evil.example` è HTML-innocuo ma pericoloso per chi clicca.

**Fix**: (1) delimitare chiaramente `free_text` nel prompt (delimitatori + istruzioni di non eseguire comandi dall'input utente); (2) **validate gli URL** emessi dalle card (schema https, dominio consentito o provenienza dai risultati SerpAPI); (3) in fase di composizione, preferire risorse con `link` proveniente dai risultati reali (cross-check) e scartare i link non riconducibili.

### SEC-5. Log injection (Rich markup) + PII nei log

**Dove**: `main.py:18` — `RichHandler(..., markup=True)`; `src/pipeline.py:70` — `logger.info("intent extracted: %s", intent.model_dump())`

- `markup=True` interpreta la sintassi Rich (`[red]`, `[link=...]`, ecc.) nei messaggi di log: un campo utente (`destination`, `free_text`) contenente tag Rich **corrompe i log** e può iniettare testo/ANSI arbitrario (log injection). Nella forma estrema può nascondere eventi o rompere gli aggregatori.
- `intent.model_dump()` logga **in chiaro** `free_text` e dati del viaggio → PII nei log (GDPR Art. 5/32).

**Fix**: `markup=False` (o logging JSON con `python-json-logger`); loggare solo un **riepilogo non sensibile** (trip_id, destinazione normalizzata) e non `free_text`/dati completi.

### SEC-6. Credenziali di default (`postgres:postgres`) e secrets management assente

**Dove**: `src/settings.py:24` — `postgres_url` default `postgresql://postgres:postgres@localhost:5432/nostos`; `src/apis/email.py:76` — `resend.api_key` globale; `.env.example` (placeholder vuoti)

- Il default di `postgres_url` contiene **credenziali note pubblicamente** in chiaro nel codice: chiunque deploya senza sovrascriverle espone il DB con credenziali banali.
- Nessun secrets manager / rotazione; le chiavi vivono solo in `.env`.

**Fix**: rimuovere i default con credenziali (fail-fast se `postgres_url` manca in produzione, es. via `Settings` con `SecretStr`); usare variabili d'ambiente esplicite in produzione (o un vault); non loggare mai le URL con password (vedi anche log `params` in `src/apis/serpapi.py:19`).

---

## 🟡 MEDIUM

### SEC-7. Information disclosure: `result=str(exc)` esposto via API

**Dove**: `src/pipeline.py:83` — `result=str(exc)`; `src/trip_store.py:34` — campo `result` in `TripResponse`; `src/routers/trips.py:43` — restituito al client

Il messaggio dell'eccezione (che può contenere dettagli interni di SerpAPI/Resend/LLM, URL, stati HTTP dei provider) viene **esposto al chiamante** tramite `GET /trips/{id}`.

**Fix**: loggare l'eccezione completa (server-side, con trip_id) e restituire solo un errore generico tipizzato (`result="EMAIL_NOT_SENT"` / `result=None` + campo `error_code`).

### SEC-8. Nessuno scanning dipendenze / CI → CVE non gestiti

**Dove**: `pyproject.toml` (dipendenze con pin `>=` aperti), nessun `pip-audit`/Dependabot/CI (confermato da AGENTS.md)

Nessun controllo automatico delle vulnerabilità note delle dipendenze (antropico, openai, fastapi, asyncpg, resend, serpapi, ecc.).

**Fix**: aggiungere `uv pip-audit` (o `pip-audit`) in CI + Dependabot; valutare pin esatti (`==`) o lockfile rigorosi (`uv.lock` già presente, da versionare e verificare).

### SEC-9. Logging/monitoring insufficiente (OWASP A09) + security headers assenti

**Dove**: `main.py` (config logging), nessun endpoint `/metrics` (vedi PERF-12)

Nessun audit trail degli eventi sensibili (chi ha creato trip, da quale IP, email inviate), nessun alerting su pattern abusivi (picchi di POST, burst verso lo stesso dominio email), nessun security header (`X-Content-Type-Options`, `HSTS`, ecc.) — per un'API JSON gli header sono meno critici, ma in caso di servizio web o proxy da configurare.

**Fix**: log strutturati con IP + trip_id; metriche su POST/GET e tassi di errore; alerting su soglie di abuso; security headers via middleware o reverse proxy.

### SEC-10. Validazione input incompleta: date, lunghezze, payload

**Dove**: `src/trip_store.py:17-27` — `start_date`/`end_date` come `Optional[str]` senza formato, `free_text` senza limite

Rispetto a SEC-3/PERF-14, l'angolo sicurezza: date e testi non validati permettono payload anomali che si propagano fino a LLM/SerpAPI/DB (costi + errori 500 non gestiti → vedi SEC-7).

**Fix**: `date` ISO con `end >= start` (validator pydantic `@field_validator`), `free_text` con `max_length` (es. 2000), `travelers_count` con tetto alto (es. `le=99`).

### SEC-11. CORS da riconfigurare in produzione + `allow_headers=["*"]`

**Dove**: `main.py:97-103`

- Di default CORS ristretto a `localhost:5500`: va **riconfigurato** con l'origine reale del frontend (GitHub Pages) — un'origine dimenticata = frontend bloccato; un'origine troppo larga = attacco cross-origin dai domini non voluti.
- `allow_headers=["*"]` con `allow_credentials=False` è accettabile ma conviene restringerlo.

**Fix**: origine di produzione esplicita; se mai si passerà a cookie/sessioni, `allow_credentials=True` richiede origini esatte (no `*`).

### SEC-12. Nessuna enforcement TLS a livello applicativo

**Dove**: `main.py:108-110` — `uvicorn.run` senza TLS; default `host=127.0.0.1`

L'app non parla mai HTTPS da sola (delegato al reverse proxy). Se esposta direttamente (o in rete interna senza proxy), le credenziali/API key viaggiano in chiaro.

**Fix**: obbligare il deployment dietro reverse proxy TLS (H1 del performance-engineer); in alternativa TLS diretto in uvicorn; disabilitare `host=0.0.0.0` senza proxy.

---

## 🔵 LOW

- **SEC-13. Errori HTTP verbose**: default FastAPI restituisce `detail` della validazione (utile) ma i 500 di Starlette in debug possono esporre traceback — in produzione `debug=False` e custom exception handler. (`main.py`)
- **SEC-14. IDOR mitigato solo dall'imprevedibilità**: `GET /trips/{trip_id}` è aperto a chiunque conosca l'UUID — accettabile a breve termine, da chiudere con l'auth (SEC-1).

---

## Piano di priorità

**Fase 1 — Bugfix critici (~1 giornata):**
1. SEC-1: autenticazione minima (API key/sessione) + autorizzazione su `GET /trips/{id}`
2. SEC-2: rate limiting su `POST /trips` (per IP + per email)
3. SEC-3: `email: EmailStr` + limite rate per destinatario
4. SEC-5: `markup=False` + log senza PII
5. SEC-7: non esporre `str(exc)` via API

**Fase 2 — Hardening (~1 giornata):**
6. SEC-4: validazione URL delle card email + delimitazione `free_text` nel prompt
7. SEC-6: rimozione default credenziali + fail-fast in produzione
8. SEC-10: validator pydantic su date/lunghezze
9. SEC-11: CORS di produzione esplicito

**Fase 3 — Procedure (~mezza giornata):**
10. SEC-8: `pip-audit` + Dependabot in CI
11. SEC-9: audit trail + alerting su abuso
12. SEC-12: TLS di rete garantito dal deploy (comune a PERF-6)

---

# `test-automator` — Copertura test, strategia di test, CI

- **Data audit**: 2026-08-13
- **Scope**: intera superficie testabile — `src/trip_store.py`, `src/pipeline.py`, `src/routers/trips.py`, `src/database.py`, `src/apis/`, `src/tools/`, `src/prompts/`, `src/settings.py`, `main.py`; toolchain di test (framework, runner, CI, coverage)
- **Metodo**: analisi delle seams di testabilità (DI, funzioni pure, protocol), identificazione di unit/integrazione/E2E per ogni modulo, verifica della toolchain presente (`pyproject.toml`, AGENTS.md)
- **Verdetto**: **Copertura test pari a zero.** Nessun framework, nessun runner, nessuna configurazione pytest, nessun CI (confermato da AGENTS.md: *"No tests, linter, typecheck, or CI exist"*). La logica di business critica (lock anti-doppia-esecuzione, orchestrazione pipeline, validazione, escape HTML) non ha nessuna verifica automatica. La buona notizia: **le seams di testabilità esistono già** (DI pulita, `LLMClient` come Protocol, funzioni pure isolate) — serve solo costruire la suite.
- **Intervento necessario**: setup toolchain pytest + prima ondata di unit test (funzioni pure, modelli, TripStore con fakeredis) + fake deterministici per LLM/SerpAPI/email → poi integrazione ed E2E. Da fare insieme ai fix strutturali (PERF-1, PERF-4) perché i test della pipeline dipendono dalla stabilità dell'ordine email→storico.

## Sommario finding

| ID | Severità | Titolo |
|---|---|---|
| TEST-1 | 🔴 CRITICAL | Nessuna infrastruttura di test: zero framework, zero CI, zero coverage |
| TEST-2 | 🟠 HIGH | Import-time side effects: `main.py` esegue argparse/`_fail_fast` a livello di modulo |
| TEST-3 | 🟠 HIGH | `TripStore` (Redis) senza test: lock, TTL, serializzazione, doppio claim |
| TEST-4 | 🟠 HIGH | `TripOrchestrator.run` senza test: happy path ed error paths della logica di business |
| TEST-5 | 🟠 HIGH | Endpoint API `/trips` senza test: validazione, 404, background task |
| TEST-6 | 🟡 MEDIUM | Funzioni pure non testate: email builder (escape XSS), normalizzatori SerpAPI, schemi tool |
| TEST-7 | 🟡 MEDIUM | Client LLM non testabili senza fake: `next()` su generator e `StopIteration` mai coperte |
| TEST-8 | 🟡 MEDIUM | Nessun ambiente di test per dipendenze esterne (Redis/Postgres) |
| TEST-9 | 🟡 MEDIUM | Nessun E2E né contract test con il frontend |
| TEST-10 | 🔵 LOW | Nessuna baseline di coverage per la gap analysis |

## Punti di forza (da preservare)

| # | Punto | Dove |
|---|---|---|
| ✅ | DI pulita via `Depends` → override delle dipendenze nei test con FastAPI TestClient | `src/dependencies.py`, `src/routers/trips.py` |
| ✅ | `LLMClient` è un Protocol → si può iniettare un fake deterministico senza toccare il prod | `src/apis/llm.py:14-17` |
| ✅ | `TripOrchestrator` riceve store/llm/email/db via costruttore → unit-testabile con fake | `src/pipeline.py:42-58` |
| ✅ | Funzioni pure isolate e senza I/O (email builder, normalizzatori, `_simplify`) | `src/apis/email.py:49-71`, `src/tools/`, `src/tools/__init__.py` |
| ✅ | Vincoli già espressi nei modelli pydantic (`Literal`, `ge=1`) → testabili come validazione | `src/trip_store.py:17-27` |
| ✅ | `asyncio.gather(..., return_exceptions=True)`: la degradazione è parte del design e quindi testabile | `src/pipeline.py:144` |
| ✅ | `TripStore` ha un'interfaccia piccola e statica → compatibile con `fakeredis` | `src/trip_store.py:41-108` |

---

## 🔴 CRITICAL

### TEST-1. Nessuna infrastruttura di test: zero framework, zero CI, zero coverage

**Dove**: `pyproject.toml` (nessuna dev-dependency di test, nessun `[tool.pytest.ini_options]`), repo (nessun file `tests/`, nessun CI), AGENTS.md (*"No tests, linter, typecheck, or CI exist"*)

Un'applicazione che invia email a clienti reali e brucia costi LLM/SerpAPI per ogni richiesta viene deployata **senza alcuna verifica automatica**. Qualsiasi regressione (modifica di `_compose_body_text`, dei normalizzatori, della validazione, del flusso di salvataggio) passa in produzione senza che nessuno la rilevi.

**Fix**: setup minimo con `uv add --dev pytest pytest-asyncio pytest-cov fakeredis`; directory `tests/` con layout `tests/unit`, `tests/integration`, `tests/e2e`; esecuzione via `uv run pytest`. CI con job test (GitHub Actions) come base per gli altri agenti.

---

## 🟠 HIGH

### TEST-2. Import-time side effects: `main.py` esegue argparse/`_fail_fast` a livello di modulo

**Dove**: `main.py:26-75` — `_parse_args()`, `PROVIDER_MODELS`, `_fail_fast()` eseguiti all'import; `src/prompts/__init__.py:8` e `src/apis/email.py:15-19` — lettura file a import-time; `src/settings.py:8` — `.env` dal CWD

Importare qualunque modulo della catena (anche solo per un unit test) può far **uscire dal processo** (SystemExit da `_fail_fast`) o fallire se un file di template/prompt manca. I test sono quindi fragili per costruzione: l'import di `src.apis.email` dipende dall'esistenza di `templates/email.html`, e l'import di `main` dipende dall'env del provider.

**Fix**: spostare parsing e fail-fast dentro `run()`/`main()` (come già richiesto da PERF-7); rendere i loader di template/prompt funzioni con fallback (es. `load_email_template()`) testabili; `get_settings` con `_env_file=None` di default nei test.

### TEST-3. `TripStore` (Redis) senza test: lock, TTL, serializzazione, doppio claim

**Dove**: `src/trip_store.py:41-108` — `create`, `get`, `claim`, `update_status`, `_to_response`

La logica anti-doppia-esecuzione (la più delicata del sistema, vedi PERF-2) e la round-trip di serializzazione (`flexible_dates` come stringa `"True"`/`"False"`, `_to_response` con cast) non hanno **nessun test**. Un refactor di `_to_response` o del formato Redis romperebbe silenziosamente tutti i trip esistenti.

**Fix**: test con `fakeredis` (async): create→get round-trip (tutti i campi, inclusi None e bool), claim acquistato vs doppio claim rifiutato, expire del lock dopo TTL, `update_status` con e senza `result`, `TripNotFoundError` su chiave mancante.

### TEST-4. `TripOrchestrator.run` senza test: happy path ed error paths della logica di business

**Dove**: `src/pipeline.py:60-192` — `run`, `_extract_intent`, `_compose_package`, `_send_email`, `_save_history`, `_compose_body_text`

È **la** logica di business: nessun test verifica che (a) con intent + SerpAPI ok l'email parta e lo storico venga salvato; (b) con tutte le ricerche vuote scatti `NoResourcesError` e nessuna email parta; (c) con LLM in errore lo status passi a `ERROR` con `result`; (d) il claim già preso faccia ritornare subito senza effetti collaterali.

**Fix**: fake `LLMClient` (in-memory deterministico), fake `EmailSender` (registra le email), fake `Database` (in-memory), fake store su fakeredis; poi test dei 4 scenari sopra. I fakes vanno in `tests/fakes.py` condivisi.

### TEST-5. Endpoint API `/trips` senza test: validazione, 404, background task

**Dove**: `src/routers/trips.py:13-45`

Nessun test verifica: payload valido → 200 + `TripResponse`; `travelers_count=0` → 422; `travelers_type` non in whitelist → 422; `GET` su trip inesistente → 404; che il background task venga effettivamente schedulato (e che al completamento lo stato diventi `DONE`).

**Fix**: `fastapi.testclient.TestClient` + `app.dependency_overrides` per store/llm/email/db (le seams di `src/dependencies.py` lo rendono banale); verifica dell'avanzamento di stato con polling su fakeredis.

---

## 🟡 MEDIUM

### TEST-6. Funzioni pure non testate: email builder (escape XSS), normalizzatori SerpAPI, schemi tool

**Dove**: `src/apis/email.py:49-71` (`_render_card`, `build_html_email`, `_e`), `src/pipeline.py:112-131` (`_compose_body_text`), `src/tools/flights.py:10-28`, `src/tools/maps.py:7-16`, `src/tools/places.py:13-23`, `src/tools/__init__.py:23-48`, `src/prompts/__init__.py`

Sono funzioni pure, deterministiche e senza I/O: il **miglior ROI** di test dell'intero progetto. In particolare:
- `_e`/`_render_card`: verifica dell'escape HTML su `href`, `name`, `desc`, `price` (mitigazione XSS di SEC-4) — oggi nessuna prova che un `item["link"]` con `"` o `<` non rompa il markup;
- `_normalize` di flights/maps/places: mappatura campi, default `"N/D"`, `flight.get("price")` senza `_eur`;
- `_simplify`/`make_ollama_schema`: semplificazione schema pydantic per grammar di Ollama (logica di parsing delicata);
- `_compose_body_text`: formato del body plain-text (numerazione, sezioni).

**Fix**: unit test tabellari (parametri) per ciascuna — nessuna dipendenza esterna, corrono in millisecondi.

### TEST-7. Client LLM non testabili senza fake: `next()` su generator e `StopIteration` mai coperte

**Dove**: `src/apis/llm.py:26-36` (`next(b for b in ...)`), `:45-55`, `:64-82`

Il percorso `response.content` senza `tool_use` (o con `function_call` assente) solleva `StopIteration` → trip in `ERROR` con messaggio incomprensibile (vedi PERF-10). Questi path d'errore **non sono mai stati eseguiti** da un test perché i client sono accoppiati ai provider reali.

**Fix**: una fake implementation di `LLMClient` (Protocol già esistente) con risposte configurabili (con/senza tool_use, JSON invalido); test dei client con `AsyncMock` dei client SDK per verificare costruzione payload e handling degli errori.

### TEST-8. Nessun ambiente di test per dipendenze esterne (Redis/Postgres)

**Dove**: `src/database.py:11-51`, `main.py:86-87`, `schema.sql`

`Database.save_trip_history` usa `asyncpg` con tipi reali (`UUID`, `date.fromisoformat`, `$14::jsonb`): nessun test verifica il mapping, il `date.fromisoformat` su date None/malformate, o la query stessa. Non esiste un modo riproducibile per lanciare Redis/Postgres nei test.

**Fix**: unit test su `date.fromisoformat`/mapping con parametri; test di integrazione con servizi reali tramite `docker compose` dedicato (o testcontainers) in CI, skip automatico se i servizi non sono disponibili in locale.

### TEST-9. Nessun E2E né contract test con il frontend

**Dove**: `docs/index.html` (post di JSON che deve combaciare con `TripCreateRequest`), `main.py:97-103` (CORS)

Il frontend mock posta JSON verso `/trips`: nessun test garantisce che il **contract dei campi** resti allineato quando `TripCreateRequest` cambia, né che il flusso completo (POST → background → status DONE → email registrata nel fake → riga in Postgres) funzioni end-to-end.

**Fix**: (1) schema contract test che valida il payload emesso da `docs/index.html` contro `TripCreateRequest` (estrazione dello schema pydantic vs oggetto del form JS); (2) un E2E con TestClient + fakes + fakeredis che attende lo stato `DONE` (con timeout) e verifica email + storico. CORS testato con origine `localhost:5500`.

### TEST-10. Nessuna baseline di coverage per la gap analysis

**Dove**: toolchain (assente)

Senza `pytest-cov`/`coverage.py` non si può misurare cosa resta scoperto, e la gap analysis (il mio stesso audit) non è replicabile nel tempo.

**Fix**: `uv run pytest --cov=src --cov-report=term-missing`; stabilire una soglia minima (es. 70% su `src/tools` e `src/apis`, 60% globale) con `fail_under` in CI; rieseguire l'audit dopo la Fase 1.

---

## 🔵 LOW

- `pyproject.toml` — niente `[tool.pytest.ini_options]` (testpaths, asyncio_mode): da aggiungere con `asyncio_mode = "auto"` per i test async senza boilerplate.
- `src/trip_store.py:100` — la serializzazione `str(...) == "True"` è fragile (vedi PERF-11): un test di round-trip la inchioderebbe al comportamento attuale e ne consentirebbe il refactor sicuro.

---

## Piano di priorità

**Fase 1 — Toolchain + unit test (~1 giornata):**
1. TEST-1: `uv add --dev pytest pytest-asyncio pytest-cov fakeredis` + layout `tests/` + CI base
2. TEST-6: unit test su tutte le funzioni pure (email builder, normalizzatori, `_simplify`, prompts)
3. TEST-3: `TripStore` su fakeredis (lock, TTL, round-trip)
4. TEST-2: spostare argparse/fail-fast in `run()` (in sinergia con PERF-7)

**Fase 2 — Logica di business (~1 giornata):**
5. TEST-4: `tests/fakes.py` (LLM/Email/Database fake) + 4 scenari di `TripOrchestrator.run`
6. TEST-5: endpoint API con TestClient + `dependency_overrides` (validazione, 404, schedulazione)
7. TEST-7: fake `LLMClient` + test degli error paths dei client

**Fase 3 — Integrazione ed E2E (~1 giornata):**
8. TEST-8: unit mapping database + integrazione con docker compose/testcontainers (skip se assenti)
9. TEST-9: contract test frontend ↔ `TripCreateRequest` + E2E flusso completo
10. TEST-10: soglia coverage in CI + gap analysis di ritorno

---

# Sezioni colleghi (in arrivo)

> Ogni agente aggiunge qui la propria sezione, con lo stesso formato:
> intestazione (`# <nome-agente> — <ambito>`), data, scope, verdetto,
> tabella finding con ID propri (es. `SEC-1`, `PERF-1`, `TEST-1`), dettagli
> con riferimenti `file:line` e piano di priorità.
