# Nostos — Proposta sogno in 3 atti (2026-09-27)

## 1. Obiettivo

La mail smette di essere inventario e diventa racconto che fa sognare:
Atto I (scena d'arrivo) → Atto II (2-3 momenti-luogo) → Atto III (invito al
follow-up umano). Logistica sobria in coda solo con dati. Il Planner a fasi
e la card-grid vanno in pensione.

## 2. Modello dati (src/core/models.py)

```python
class DreamScene(BaseModel):
    title: str = Field(description="Titolo evocativo della scena, es. 'Heraklion di sera'")
    prose: str = Field(description="3-5 frasi sensoriali: luce, cibo, suoni, materia. Mai filler")
    place_links: list[str] = Field(default_factory=list, description="URL verificati citati nella scena")

class DreamContent(BaseModel):
    subject: str = Field(description="Oggetto breve e personale")
    arrival: str = Field(description="Atto I: scena d'apertura sensoriale, 2-3 frasi")
    scenes: list[DreamScene] = Field(description="Atto II: 2 o 3 scene")
    logistics: str = Field(default="", description="Volo+prezzi in una riga sobria, o vuoto")
```

## 3. Regole di scrittura (prompt)

Ogni scena: almeno 2 dettagli sensoriali concreti legati al brief; zone
evocabili senza link; ogni NOME PROPRIO di locale/struttura deve avere link
verificato. Vietati: filler ('possibile sosta', 'da inserire', 'pratico',
'una base per', 'coerente con'), aggettivi vuoti da soli ('bello',
'incantevole', 'meraviglioso'), frasi su dati mancanti, fasi stirate.
Minimo 2 scene valide, massimo 3.

## 4. Validazione (codice, src/core/orchestrator.py)

- Link: solo allow-list curata (come oggi); scena con link fuori lista → scartata.
- Nomi propri nuovi: estrazione ingenua (parole capitalizzate non a inizio
  frase, assenti dal corpus) → se presenti, 1 retry con istruzione mirata.
- Gate anti-generico esteso: filler + aggettivi vuoti + <40 caratteri per scena.
- Se le scene valide sono <2 → NoResourcesError (niente mail).
- `_compose_dream` sostituisce `_compose_email`; Planner, sanitize_plan,
  TripPlan e fallback deterministico rimossi dal path (test aggiornati).

## 5. Template (src/services/templates/email.html)

Masthead + kicker + trip_summary (tengo) → $arrival → scene (titolo 20px +
prosa + link discreti "Vedi →") → $logistics_section (riga sobria o assente)
→ rental (tengo) → bozza + CTA follow-up (tengo) → firma. Via: card-grid,
fasi-giorno, pill, box doppi, travel box. Testo puro gemello.

## 6. Testing

Struttura atti (2-3 scene, ordine), link solo allow-list, divieto
filler/aggettivi (unit sul gate), nomi propri → retry, <2 scene → abort,
suite intera. File: models, prompts, orchestrator, email.py, template, test.
Niente API/DB/worker. Jev-router invariato (le 6 domande restano).
