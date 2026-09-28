# Nostos — Lettera (2026-09-28)

## 1. Obiettivo

La mail diventa una lettera personale che fa sognare: apertura-scena,
2-3 momenti in prosa, lista nominata dei luoghi, invito al follow-up umano.
Niente inventario, niente fasi, niente header burocratici. Sacri solo voce
editoriale italiana e firma fondatori.

## 2. Modello dati (src/core/models.py)

```python
class LetterMoment(BaseModel):
    prose: str = Field(description="Prosa sensoriale continua, fatti tessuti dentro, mai liste")
    place_links: list[str] = Field(default_factory=list, description="URL verificati citati")

class LetterContent(BaseModel):
    subject: str = Field(description="Oggetto breve e personale")
    opening: str = Field(description="Scena d'apertura sensoriale, 2-3 frasi")
    moments: list[LetterMoment] = Field(description="2 o 3 momenti")
    closing: str = Field(description="Invito al passo umano, 1-2 frasi")
```

## 3. Regole di scrittura (prompt)

Prosa continua sensoriale (luce, cibo, suoni, materia); fatti del viaggio
(destinazione, date, viaggiatori) tessuti dentro, mai in header — niente
"coppia (2)". Zone evocabili senza link; ogni NOME PROPRIO di locale o
struttura deve avere link verificato. Vietati: filler ('possibile sosta',
'da inserire', 'pratico', 'una base per', 'coerente con'), aggettivi vuoti
da soli ('bello', 'incantevole', 'meraviglioso'), frasi su dati mancanti,
elenchi, fasi, prezzi ostentati. Minimo 2 momenti validi, massimo 3.

## 4. Validazione (codice)

Riuso gate esistenti (`is_generic_scene`, `find_new_proper_nouns`,
allow-list): link solo verificati; nomi nuovi → 1 retry; filler → 1 retry;
<2 momenti validi → NoResourcesError. Lista luoghi costruita in codice dai
link citati nei momenti (nomi dai dati, mai orfani, mai duplicati). Voli curati
e noleggi van, se presenti, entrano come voci della lista luoghi
("Volo … – vedi", "Noleggio van … – vedi"), mai in sezioni separate.

## 5. Template e rendering

Masthead piccolo → apertura → momenti → lista luoghi → invito + bottone
"Parliamone insieme" → firma. Via: trip summary, fasi, card, box, pill,
label inventario, striscia logistica, travel box, fonti separate. Renderer
piccoli in email.py; testo puro gemello. Jev-router, research, worker, API,
DB invariati.
