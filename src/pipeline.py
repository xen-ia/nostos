import asyncio
import logging
from typing import Optional

from pydantic import BaseModel

from src.apis.llm import LLMClient
from src.bases.orchestrator import BaseOrchestrator
from src.trip_store import TripResponse, TripStatus, TripStore
from src.apis import flights, maps, places
from src.apis.email import EmailSender
from src.database import Database

logger = logging.getLogger("nostos.pipeline")


class TripIntent(BaseModel):
    destination: Optional[str] = None
    departure_airport_code: Optional[str] = None
    destination_airport_code: Optional[str] = None
    interests: list[str] = []
    style: list[str] = []
    pace: Optional[str] = None
    constraints: list[str] = []


TRIP_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "destination": {
            "type": ["string", "null"],
            "description": "Destinazione se esplicita o chiaramente deducibile, altrimenti null",
        },
        "departure_airport_code": {
            "type": ["string", "null"],
            "description": (
                "Codice IATA dell'aeroporto di partenza (es. MXP, BCN) se deducibile "
                "dalla richiesta, altrimenti null"
            ),
        },
        "destination_airport_code": {
            "type": ["string", "null"],
            "description": (
                "Codice IATA dell'aeroporto della destinazione (es. FCO, DPS, CTA) se "
                "deducibile, altrimenti null"
            ),
        },
        "interests": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Interessi concreti menzionati: es. trekking, cibo locale, storia, mare",
        },
        "style": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Stile/atmosfera del viaggio. Presta particolare attenzione a segnali di "
                "rifiuto del turismo di massa (es. 'non i soliti posti', 'fuori dalle rotte "
                "turistiche', 'autentico', 'lontano dalle folle') — quando presenti, includili "
                "sempre esplicitamente qui."
            ),
        },
        "pace": {
            "type": ["string", "null"],
            "description": "Ritmo del viaggio: rilassato, moderato, intenso — o null se non deducibile",
        },
        "constraints": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Vincoli espliciti: dieta, accessibilità, bambini, animali",
        },
    },
    "required": ["interests", "style", "constraints"],
}

EMAIL_CONTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "description": "Oggetto dell'email, breve e personale"},
        "body": {
            "type": "string",
            "description": (
                "Corpo dell'email in italiano, TESTO PIANO: niente markdown, niente asterischi, "
                "niente trattini per elenchi, niente hashtag — solo testo e andate a capo. "
                "La firma deve essere 'Xen-IA, assistente AI'. Deve: "
                "1) presentarsi come Xen-IA, assistente AI, in modo onesto ma accattivante, mai banale; "
                "2) in apertura far capire di aver compreso l'intento e i desideri del viaggiatore "
                "(interessi, stile, ritmo), con un tono più discorsivo e un po' prolisso; "
                "3) offrire 2-3 spunti concreti e consultabili, basati sui dati reali forniti, con i "
                "relativi link dove utile; "
                "4) chiudere invitando a rispondere. Massimo ~180 parole, tenendo le parti narrative "
                "più ampie degli elenchi."
            ),
        },
    },
    "required": ["subject", "body"],
}


class TripOrchestrator(BaseOrchestrator):
    LOCK_TTL_SECONDS = 300

    def __init__(
        self,
        store: TripStore,
        llm_client: LLMClient,
        email_sender: EmailSender,
        database: Database,
        trip_id: str,
    ):
        self._store = store
        self._llm = llm_client
        self._email = email_sender
        self._db = database
        self._trip_id = trip_id

    async def run(self) -> None:
        claimed = await self._store.claim(self._trip_id, ttl_seconds=self.LOCK_TTL_SECONDS)
        if not claimed:
            return

        try:
            trip = await self._store.get(self._trip_id)
            await self._store.update_status(self._trip_id, TripStatus.RUNNING)

            intent = await self._extract_intent(trip)
            logger.info("intent estratto: %s", intent.model_dump())

            email_content, package = await self._compose_package(trip, intent)

            await self._store.update_status(self._trip_id, TripStatus.DONE, result=email_content["body"])
            await self._send_email(trip, email_content)
            await self._save_history(trip, email_content, package)
            logger.info("trip %s completato: email inviata e storico salvato", self._trip_id)

        except Exception as exc:
            logger.exception("trip %s fallito", self._trip_id)
            await self._store.update_status(self._trip_id, TripStatus.ERROR, result=str(exc))

    async def _save_history(self, trip: TripResponse, email_content: dict, package: dict) -> None:
        await self._db.save_trip_history(
            trip_id=trip.id,
            email=trip.email,
            destination=trip.destination,
            start_date=trip.start_date,
            end_date=trip.end_date,
            flexible_dates=trip.flexible_dates,
            travelers_count=trip.travelers_count,
            travelers_type=trip.travelers_type,
            budget_range=trip.budget_range,
            departure_location=trip.departure_location,
            free_text=trip.free_text,
            email_subject=email_content["subject"],
            email_body=email_content["body"],
            package=package,
        )

    async def _send_email(self, trip: TripResponse, email_content: dict) -> None:
        await self._email.send(to=trip.email, subject=email_content["subject"], body=email_content["body"])


    async def _extract_intent(self, trip: TripResponse) -> TripIntent:
        prompt = f"""Estrai le informazioni di viaggio da questa richiesta.

        Destinazione indicata nel form: {trip.destination or "non specificata"}
        Luogo di partenza indicato nel form: {trip.departure_location or "non specificato"}
        Testo libero dell'utente: "{trip.free_text}"

        Se possibile, riporta anche i codici IATA di partenza e destinazione.
        """
        raw = await self._llm.extract_json(prompt, TRIP_INTENT_SCHEMA)
        return TripIntent.model_validate(raw)

    async def _compose_package(self, trip: TripResponse, intent: TripIntent) -> tuple[dict, dict]:
        destination = intent.destination or trip.destination
        departure_code = intent.departure_airport_code or trip.departure_location
        destination_code = intent.destination_airport_code or destination
        results = await asyncio.gather(
            flights.search(departure_code, destination_code, trip.start_date, trip.end_date),
            maps.research(destination, intent.interests),
            places.search(destination, intent.interests, intent.style),
            return_exceptions=True,
        )
        flights_list, maps_list, places_list = (r if not isinstance(r, Exception) else [] for r in results)

        for label, result in (("voli", results[0]), ("poi", results[1]), ("alloggi", results[2])):
            if isinstance(result, Exception):
                logger.warning("%s: errore %s", label, type(result).__name__)
            else:
                logger.info("%s: %d risultati", label, len(result))

        package = {
            "intent": intent.model_dump(),
            "flights": flights_list[:3],
            "maps": maps_list[:3],
            "places": places_list[:3],
        }

        prompt = f"""Sei un travel curator che lavora per Xen-IA, un'assistente AI che aiuta a
        comporre viaggi autentici. Scrivi un'email a un potenziale viaggiatore.

        Regole per l'email:
        - TESTO PIANO: niente markdown, niente asterischi, trattini o hashtag. Solo testo e
          andate a capo (Gmail non renderizza il markdown);
        - firma con 'Xen-IA, assistente AI'. Non usare il nome Nostos per presentarti: presentati
          proprio come Xen-IA, e fai capire fin dall'inizio che è un'AI a scrivere — con schiettezza
          ma in modo accattivante, non banale;
        - in apertura: mostra di aver capito davvero cosa cerca il viaggiatore (i suoi interessi,
          lo stile, il ritmo), con un tono discorsivo e leggermente prolisso, per creare vicinanza;
        - proponi 2-3 spunti concreti e consultabili, citando solo dati reali forniti e i relativi
          link (es. volo con prezzo e link, un punto di interesse, un alloggio con prezzo e link);
        - non inventare dati; se una sezione è vuota non forzarla;
        - chiudi invitando a rispondere. Parti narrative più ampie delle parti elenco, il tutto
          intorno alle ~180 parole.

        Contesto viaggio:
        Interessi: {', '.join(intent.interests) or 'non specificati'}
        Stile ricercato: {', '.join(intent.style) or 'non specificato'}
        Ritmo: {intent.pace or 'non specificato'}

        Dati reali raccolti (usa questi, non inventarne di nuovi):
        Voli (top): {flights_list if flights_list else 'nessun volo trovato'}
        Punti di interesse (top): {maps_list if maps_list else 'nessun punto di interesse trovato'}
        Alloggi (top): {places_list if places_list else 'nessun alloggio trovato'}
        """
        email_content = await self._llm.extract_json(prompt, EMAIL_CONTENT_SCHEMA)
        return email_content, package