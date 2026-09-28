"""LLM tool-call extraction schemas: TripIntent and letter content."""
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
    travel_mode: Optional[str] = Field(
        default=None,
        description=(
            "Modalità di viaggio prevalente: 'fixed' (base fissa), 'road_trip' (tappe in auto/moto), "
            "'van_life' (dormire nel veicolo lungo il percorso), 'sailing' (barca a vela/catamarano), "
            "'mixed' (combinazione). Dedurre dal free_text e da come l'utente descrive gli spostamenti in loco."
        ),
    )
    accommodation_style: Optional[str] = Field(
        default=None,
        description=(
            "Stile di pernottamento preferito: 'homestay', 'hotel', 'van', 'camping', 'boat', 'mixed'. "
            "Se travel_mode è 'van_life' → 'van'; se 'sailing' → 'boat'; se 'road_trip' → 'van' o 'hotel'; "
            "altrimenti 'homestay'/'hotel' per 'fixed'."
        ),
    )
    mobility_preferences: list[str] = Field(
        default_factory=list,
        description=(
            "Mezzi di spostamento in loco esplicitamente menzionati o fortemente impliciti: "
            "'auto', 'moto', 'bici', 'barca', 'trasporti_pubblici', 'a_piedi'. "
            "Se l'utente dice 'noleggiare un van/jeep e dormire lungo il percorso' → ['auto', 'van']. "
            "Se 'vorrei noleggiare una barca a vela' → ['barca']. Estrapolare dal free_text."
        ),
    )
    needs_flights: bool = Field(
        default=True,
        description=(
            "True se il viaggiatore deve raggiungere la destinazione con un volo: "
            "paese diverso dalla partenza, isole, 'noleggio quando arrivo', lunghe distanze. "
            "False solo quando è chiaro che resta in zona (stessa regione, on the road da casa). "
            "Nel dubbio con paesi diversi → True."
        ),
    )
    budget_sensitive: bool = Field(
        default=False,
        description="True se il budget è esplicitamente ristretto (limitato, max, economico)",
    )
    flight_rationale: str = Field(
        default="",
        description="In italiano: perché i voli servono oppure no per questo viaggio",
    )


class LetterMoment(BaseModel):
    prose: str = Field(description="Prosa sensoriale continua, fatti tessuti dentro, mai liste")
    place_links: list[str] = Field(default_factory=list, description="URL verificati citati nel momento")


class LetterContent(BaseModel):
    subject: str = Field(description="Oggetto breve e personale")
    opening: str = Field(description="Scena d'apertura sensoriale, 2-3 frasi")
    moments: list[LetterMoment] = Field(description="2 o 3 momenti")
    closing: str = Field(description="Invito al passo umano, 1-2 frasi")


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


class ResolvedPlace(BaseModel):
    name: str = Field(description="Nome della meta concreta (isola, città)")
    country: str = Field(default="", description="Paese/Territorio")
    airport_code: Optional[str] = Field(default=None, description="Codice IATA principale della meta")


class ResolvedDestinations(BaseModel):
    destinations: list[ResolvedPlace] = Field(
        default_factory=list,
        description="Max 2 mete concrete; vuota se la destinazione era già specifica",
    )
    rationale: str = Field(default="", description="In italiano: perché queste mete per questo viaggiatore")


class DepartureAirports(BaseModel):
    codes: list[str] = Field(default_factory=list, description="1..4 codici IATA candidati di partenza")
