import asyncio
from typing import Optional

from pydantic import BaseModel

from src.apis.llm import LLMClient
from src.bases.orchestrator import BaseOrchestrator
from src.trip_store import TripResponse, TripStatus, TripStore
from src.apis import flights, maps, places
from src.apis.email import EmailSender
from src.database import Database


class TripIntent(BaseModel):
    destination: Optional[str] = None
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
            "description": "Corpo dell'email in italiano, max 150 parole, tono caldo. "
                           "Chiudi invitando a rispondere per fissare una call, non con un link.",
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
            email_content = await self._compose_package(trip, intent)

            await self._store.update_status(self._trip_id, TripStatus.DONE, result=email_content["body"])
            await self._send_email(trip, email_content)
            await self._save_history(trip, email_content)

        except Exception as exc:
            await self._store.update_status(self._trip_id, TripStatus.ERROR, result=str(exc))

    async def _save_history(self, trip: TripResponse, email_content: dict) -> None:
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
        )

    async def _send_email(self, trip: TripResponse, email_content: dict) -> None:
        await self._email.send(to=trip.email, subject=email_content["subject"], body=email_content["body"])


    async def _extract_intent(self, trip: TripResponse) -> TripIntent:
        prompt = f"""Estrai le informazioni di viaggio da questa richiesta.

        Destinazione indicata nel form: {trip.destination or "non specificata"}
        Testo libero dell'utente: "{trip.free_text}"
        """
        raw = await self._llm.extract_json(prompt, TRIP_INTENT_SCHEMA)
        return TripIntent.model_validate(raw)

    async def _compose_package(self, trip: TripResponse, intent: TripIntent) -> dict:
        flights_res, maps_res, places_res = await asyncio.gather(
            flights.search(trip.departure_location, intent.destination or trip.destination, trip.start_date, trip.end_date),
            maps.research(intent.destination or trip.destination, intent.interests),
            places.search(intent.destination or trip.destination, intent.interests, intent.style),
        )

        prompt = f"""Sei un travel curator di Nostos, agenzia che valorizza viaggi autentici e
        sostenibili, lontani dal turismo di massa. Componi un insight da inviare via email a un
        potenziale viaggiatore. Non presentarlo come un pacchetto finito — è uno spunto per aprire
        una conversazione.

        Interessi: {', '.join(intent.interests) or 'non specificati'}
        Stile ricercato: {', '.join(intent.style) or 'non specificato'}
        Volo di esempio: {flights_res[0]}
        Punto di interesse: {maps_res[0]}
        Esperienza/alloggio: {places_res[0]}
        """
        return await self._llm.extract_json(prompt, EMAIL_CONTENT_SCHEMA)