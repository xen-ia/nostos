"""LLM tool-call extraction schemas: TripIntent and EmailContent."""
from typing import Optional

from pydantic import BaseModel, Field


class TripIntent(BaseModel):
    destination: Optional[str] = Field(
        default=None,
        description="Destinazione se esplicita o chiaramente deducibile, altrimenti null",
    )
    departure_airport_code: Optional[str] = Field(
        default=None,
        description="Codice IATA dell'aeroporto di partenza (es. MXP, BCN) se deducibile dalla richiesta, altrimenti null",
    )
    destination_airport_code: Optional[str] = Field(
        default=None,
        description="Codice IATA dell'aeroporto della destinazione (es. FCO, DPS, CTA) se deducibile, altrimenti null",
    )
    interests: list[str] = Field(
        default_factory=list,
        description="Interessi concreti menzionati: es. trekking, cibo locale, storia, mare",
    )
    style: list[str] = Field(
        default_factory=list,
        description=(
            "Stile/atmosfera del viaggio. Presta particolare attenzione a segnali di rifiuto del turismo "
            "di massa (es. 'non i soliti posti', 'fuori dalle rotte turistiche', 'autentico', 'lontano "
            "dalle folle') — quando presenti, includili sempre esplicitamente qui."
        ),
    )
    pace: Optional[str] = Field(
        default=None,
        description="Ritmo del viaggio: rilassato, moderato, intenso — o null se non deducibile",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Vincoli espliciti: dieta, accessibilità, bambini, animali",
    )


class EmailResource(BaseModel):
    name: str = Field(
        description="Nome della risorsa, preso PAROLA PER PAROLA dai dati reali forniti"
    )
    description: str = Field(
        default="",
        description="Breve dettaglio descrittivo in italiano",
    )
    price: str = Field(
        default="",
        description="Prezzo indicato, es. '320 EUR' o '95 EUR/notte', preso dai dati reali",
    )
    link: str = Field(description="URL dalla risorsa reale fornita")


class EmailContent(BaseModel):
    subject: str = Field(description="Oggetto dell'email, breve e personale")
    opening: str = Field(
        description="Una sola frase d'attacco non banale che aggancia subito il lettore. Non presentarti come AI."
    )
    understanding: str = Field(
        description=(
            "1-2 frasi secche che dimostrano di aver capito cosa cerca il viaggiatore: riprendi interessi, "
            "stile e ritmo della richiesta, con vicinanza ma senza prolissità."
        )
    )
    resources: list[EmailResource] = Field(
        description=(
            "3 spunti concreti, tra voli/poi/alloggi forniti, presi PAROLA PER PAROLA dai dati reali. "
            "Niente di inventato. Se i dati sono insufficienti, inserisci meno voci."
        )
    )


class DateWindow(BaseModel):
    start: str = Field(description="Inizio finestra candidata, ISO YYYY-MM-DD")
    end: str = Field(description="Fine finestra candidata, ISO YYYY-MM-DD")
    rationale: str = Field(default="", description="Perché questa finestra è adatta al viaggio")


class PeriodPlan(BaseModel):
    windows: list[DateWindow] = Field(
        default_factory=list,
        description="Massimo 2 finestre temporali candidate, entrambe nel futuro",
    )


class TargetQuery(BaseModel):
    query: str = Field(description="Query di ricerca mirata, stessa lingua della destinazione")
    based_on: str = Field(default="", description="Anchor dall'esplorazione da cui deriva la query")


class TargetQueries(BaseModel):
    queries: list[TargetQuery] = Field(
        default_factory=list,
        description="Massimo 4 query mirate, ognuna derivata da un anchor dell'esplorazione",
    )


class Curation(BaseModel):
    flight_indices: list[int] = Field(default_factory=list, description="Indici dei voli selezionati")
    poi_indices: list[int] = Field(default_factory=list, description="Indici dei POI selezionati")
    stay_indices: list[int] = Field(default_factory=list, description="Indici degli alloggi selezionati")
    rationale: str = Field(default="", description="Breve motivazione delle scelte, in italiano")