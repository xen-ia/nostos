# Nostos — Fase 2: itinerario strutturato (2026-09-20)

## 1. Obiettivo

L'email finale guadagna una sezione itinerario (esempio approvato: Creta van 30gg →
oggetto dedicato, apertura, understanding, hero volo, 4 fasi condensate con card
grounded + transizioni libere, noleggio van, resto card, fonti, firma). Il Planner LLM
decide la granularità da durata + travel_mode; mai 30 sezioni. Base: branch
`feature/jev-itinerary`, sopra Jev-centrale fase 1 (router/scorer/gate + fallback).

## 2. Modello dati (src/core/models.py)

```python
class DayStop(BaseModel):
    day_label: str        # es. "Giorni 1-7 · Heraklion e dintorni" — deciso dal Planner
    stop_refs: list[int]  # indici zero-based nel corpus curato (convenzione Curation)
    transition: str = ""  # percorso libero in italiano, MAI link/URL

class TripPlan(BaseModel):
    days: list[DayStop]   # max 7 voci; il Planner condensa i trip lunghi in fasi
    rationale: str = ""   # perché questa articolazione, in italiano
```

Validazione (codice, non prompt): `stop_refs` fuori range scartati con warning
(come `pick` in `_curate`); `transition` con URL rilevato (`https?://|www\.`)
→ campo svuotato, tappa tenuta; piano con zero tappe valide → email senza sezione
itinerario (mai abortire il trip). Piano persistito in `package["trip_plan"]`.

## 3. Planner (src/core/prompts/__init__.py: build_plan_prompt)

Nuovo `extract()` dopo `_curate`, prima di `_compose_email`. Input: trip, intent,
blocchi numerati curati (stesso rendering `[F/M/P]n`), durata giorni da
start/end_date (se assenti: nessuna sezione itinerario, email come fase 1).
Istruzioni: max 7 voci; ogni voce 1-3 `stop_refs` solo dagli ID listati;
`day_label` con intervallo + nome zona; `transition` una riga di logica
spostamento/pernottamento senza inventare servizi e senza URL; coprire
arrivo→permanenza→rientro; per `fixed` preferire fasi per zone, per
`van_life`/`road_trip` per tratte con pernottamenti a bordo, per `sailing`
per tratte costiere. Fallback: `JevError`/eccezione o piano vuoto → si salta
la sezione (flag `has_itinerary=False`), mai retry infinito (1 solo tentativo,
niente retry come le card che hanno retry dedicato).

## 4. Composer integration (src/core/orchestrator.py)

`_compose_email` riceve `trip_plan` opzionale: le card `resources` restano
generate come oggi dall'intero curato (l'itinerario riusa gli stessi link,
non aggiunge risorse); il piano aggiunge solo la sezione. `sections_map`
invariato. `validate_resources` invariato. Body text: dopo "Punti di partenza"
e prima del travel box, sezione "L'itinerario" con `day_label` + nomi tappe
+ transizioni + link già mostrati (niente duplicazione link nuovi).

## 5. Template (src/services/templates/email.html + email.py)

Nuovo placeholder `$itinerary_section` tra `$resource_groups` e
`$rental_section`. Renderer `_render_itinerary(plan, resources_by_link)` in
`email.py`: heading `L'itinerario` + per voce `day_label` + card compatte
riuso `_render_card` (stessi CSS) + transizione in corsivo. Voce con zero card
valide → solo label + transizione. Piano assente → stringa vuota.
`build_html_email` e `_compose_body_text` invariati salvo la sezione.

## 6. Jev gate

Il piano passa per lo scorer/gate esistente: score fit per voce (opzionale fase 2,
default: gate solo su confidenza media Planner non disponibile → si accetta il
piano se validazione codice ok). Nessuna nuova domanda Jev obbligatoria in fase 2;
`tool_calls` logga `{"engine": "jev-itinerary", "days": n}` o lo skip.

## 7. Testing

- `tests/test_trip_plan.py`: validazione `stop_refs` out-of-range, strip URL da
  `transition`, piano vuoto → skip sezione, cap 7 voci.
- `tests/test_email_rendering.py` (extend): sezione itinerario con card riusate,
  voce senza card, piano assente → nessuna sezione.
- Fixture Creta van: piano 4 fasi atteso da prompt finto (FakeLLM), email contiene
  "Giorni 1-7" e i link delle card senza duplicati nuovi.
- Contract test invariato (input API invariato). Full suite verde.

## 8. Rollout

Dietro nessun flag (sezione puramente additiva, skip silenzioso se piano vuoto).
Fase 1 resta fallback: con `llm-fallback` il Planner gira comunque su LLM.
