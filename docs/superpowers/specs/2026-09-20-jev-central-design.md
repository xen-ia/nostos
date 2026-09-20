# Nostos — Jev-centrale design (2026-09-20)

## 1. Contesto e obiettivo

Flusso attuale (`src/core/orchestrator.py`): `intent → period → geo x2 → target` (6-7 `extract()` LLM sequenziali) → SerpAPI flights/maps/places → `curate` → `_compose_email` → template `src/services/templates/email.html`.

Dolore: email finale generica, struttura fissa, pipeline frammentata lenta/costosa/fragile sul JSON.

Obiettivo fase 1: Jev (TypeSafe AI, System One, rel. 2026-09-15) diventa orchestratore decisionale; LLM resta solo dove serve generare testo italiano. Task ricalibrata:
- (A) voli utili ed economici verso il posto;
- (B) cose da fare in base al tipo di viaggio.

Fuori scope fase 1: nuovo modello output `TripPlan` giorno-per-giorno (fase 2 sopra questo scheletro), refactor DB/API, frontend `docs/index.html`.

## 2. Perché Jev qui (e dove no)

Jev non genera testo: `POST /v1/systemone`, input `state + questions`, output decisioni tipate con probabilità (bool / choice / score), 70-500ms, $0.042/M input, output free, early access con waitlist. Verificato via docs.typesafe.ai + LangChain 2026-09-17/18.

- Va su Jev: `travel_mode` (fixed/road_trip/van_life/sailing/mixed), `pace`, `accommodation_style`, `needs_flights` bool, `avoids_crowds` bool, `budget_sensitive` bool, scoring candidati voli/POI/stay, quality-gate con soglie.
- Resta su LLM: `TargetQueries.query` (4 stringhe inventate), `PeriodPlan` finestre date, nomi di mete nuove quando destinazione vaga, `flight_rationale` / `resolve_rationale` / `EmailContent` (subject/opening/understanding/descriptions) e futura narrativa itinerario.
- `interests/style/mobility` passano a Jev solo dopo tassonomia chiusa (20-30 etichette); finché open-ended restano LLM.

Alternativa scartata: singolo ReAct OpenAI "cerca finché interessante poi HTML". Senza stopping criterion rompe timeout worker (60s SerpAPI/LLM, lease 300s), aumenta genericità e allucinazioni URL, rompe test deterministici. La validazione esistente (`build_allowed_resources`, `validate_resources` + retry, `_is_junk_link`, `strip_bracket_ids`) va tenuta.

## 3. Architettura

```
TripCreateRequest JSON ── state verbatim ─▶ [Jev Router: 1 call, 6-8 domande parallele]
  travel_mode: choice | needs_flights: bool | pace: choice
  avoids_crowds: bool | stay_fit: choice | budget_sensitive: bool
      │
      ├─ Task A voli ─▶ SerpAPI flights (codice esistente: _flight_windows + _build_flight_combos)
      │                  ▶ Jev Scorer (score utilità per volo) + sort price_eur in codice ▶ best
      └─ Task B POI ──▶ LLM text-node (solo 4 query stringa) ▶ SerpAPI maps/places
                        ▶ Jev Scorer (score fit per POI/stay) ▶ top-3
                        ▶ LLM text-node (rationale IT + EmailContent)
                        ▶ Jev quality-gate (soglie) ▶ send
```

Componenti:
- `DecisionClient` nuovo in `src/services/apis/` (adapter `/v1/systemone`, `model: jev-1.13.0` pinnato, mai alias `jev-latest`). Separato da `LLMClient`; protocollo diverso da `extract()`.
- `LLMClient` esistente (Anthropic/OpenAI/Ollama via `build_llm_client`) ridotto a 2 nodi foglia: query-generator + composer.
- `TripOrchestrator` slim: chiama Jev, esegue SerpAPI in parallelo dal codice, chiama LLM solo per testo.
- Flag `NOSTOS_DECISION_PROVIDER=jev|llm-fallback`: fallback automatico agli `extract()` attuali se Jev non raggiungibile.

## 4. Data flow calibrato (3 esempi)

Es.1 Creta van — in: `destination Creta, departure Italy, 2027-07-30/08-30, flexible false, free_text "cibo e tradizioni locali, mare e relax, ritmo lento, lontano dalle folle, van/jeep"`. Jev atteso: `van_life 0.92, needs_flights true 0.88, pace rilassato 0.90, avoids_crowds true 0.87, stay_fit van 0.91`. A: `[MXP,BGY,VRN]x[HER,CHQ]` finestra esatta → score utilità (diretto+date) + min prezzo. B: query `campervan parking south Crete, traditional taverna Lassithi, quiet beach camping Crete` → score fit (quiete+cibo+mare), scarta hotel lusso. Out: hero volo + card van/camping + box "Vita in van".

Es.2 Parigi fisso — in: `Parigi, partenza Milano, "musei, bistrot, hotel centrale, ritmo moderato"`. Jev: `fixed 0.89, needs_flights true 0.78, pace moderato, avoids_crowds false, stay hotel`. A: `MXP/LIN/BGY→CDG/ORY`. B: `small museum Marais, bistrot Saint-Germain` → premia centrale + rating ≥4.0.

Es.3 Vago budget — in: `destination null, "mare caldo a ottobre, lontano dalle folle, budget limitato"`. Jev: `budget_sensitive true 0.85, avoids_crowds true, fixed`. LLM propone 2 finestre ottobre + 2 mete candidate; Jev sceglie (choice, non inventa). Pesi: prezzo voli x2, stay penalizza hotel costosi, premia homestay/camping.

Regola: Jev non inventa mai nomi/URL/date — decide ramo e pesi; LLM genera solo stringhe.

## 5. Error handling e osservabilità

- Soglie: `>0.85` autonomo, `0.6-0.85` log + procedi, `<0.6` fallback a `extract()` LLM di verifica.
- Timeout Jev 5s; singola call parallela quindi latenza quasi costante all'aggiunta di domande; ogni domanda valutata isolata (no context-rot).
- Armor invariato: allow-list + `validate_resources` + retry, junk-filter, strip bracket IDs `[F/M/P]n`, cap corpus (`CORPUS_CAP=8`, max 3 pick per categoria).
- Log in `package.tool_calls`: engine, params, `model` versioned ID che ha risposto, probabilità, soglia applicata, ramo fallback. Persistito via `save_trip_history` invariato.
- Benchmark vendor (193x faster / 444x cheaper) non verificati da terzi; nessuna conferma accuratezza italiano; immagini non supportate; max 255 scelte per decisione (two-stage scoring sopra).

## 6. Testing

- Fixture calibrazione dai 3 esempi: JSON in → decisioni attese → query SerpAPI attese → pesi scorer.
- Mock `DecisionClient` a probabilità fisse per rami autonomo/retry/fallback senza rete.
- Test fallback: Jev 429/timeout/waitlist → path LLM esistente verde.
- Test scorer: ordinamento utilità+prezzo (voli), fit+diversità aree e no-doppie catene (POI/stay).
- Invariati in fase 1: contract test `tests/test_contract.py`, template email, `trip_history`/`feedback`.

## 7. Rollout

Fase 1 (questa spec): `DecisionClient` + flag + router/scorer/gate, 2 nodi LLM, fixture 3 esempi. Fase 2 (separata): `TripPlan` giorno-per-giorno sopra stesso scheletro.
