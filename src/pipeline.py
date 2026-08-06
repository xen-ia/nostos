import asyncio
import logging
from typing import Optional

from pydantic import BaseModel

from src.apis.llm import LLMClient
from src.bases.orchestrator import BaseOrchestrator
from src.trip_store import TripResponse, TripStatus, TripStore
from src.apis import flights, maps, places
from src.apis.email import EmailSender, build_html_email
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
        "subject": {
            "type": "string",
            "description": "Oggetto dell'email, breve e personale",
        },
        "opening": {
            "type": "string",
            "description": (
                "Frase d'attacco non banale che aggancia subito il lettore, ~50 parole in "
                "2-3 frasi. Non presentarti come AI qui."
            ),
        },
        "understanding": {
            "type": "string",
            "description": (
                "2-3 frasi, tono discorsivo e un po' prolisso, in cui dimostri di aver capito "
                "davvero cosa cerca il viaggiatore: riprendi interessi, stile e ritmo della richiesta."
            ),
        },
        "resources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nome della risorsa, preso PAROLA PER PAROLA dai dati reali forniti"},
                    "description": {"type": "string", "description": "Breve dettaglio descrittivo in italiano"},
                    "price": {"type": "string", "description": "Prezzo indicato, es. '320 EUR' o '95 EUR/notte', preso dai dati reali"},
                    "link": {"type": "string", "description": "URL dalla risorsa reale fornita"},
                },
                "required": ["name", "link"],
            },
            "description": (
                "3 spunti concreti, tra voli/poi/alloggi forniti, presi PAROLA PER PAROLA dai dati "
                "reali. Niente di inventato. Se i dati sono insufficienti, inserisci meno voci."
            ),
        },
        "honest_note": {
            "type": "string",
            "description": (
                "1-2 frasi: accenna che l'email è stata preparata con il supporto di un assistente "
                "AI (senza dire il nome), ricorda che prezzi/date vanno verificati, invita a rispondere."
            ),
        },
    },
    "required": ["subject", "opening", "understanding", "resources", "honest_note"],
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

            email_content, body_text, body_html, package = await self._compose_package(trip, intent)

            await self._store.update_status(self._trip_id, TripStatus.DONE, result=body_text)
            await self._send_email(trip, email_content, body_text, body_html)
            await self._save_history(trip, email_content, body_text, package)
            logger.info("trip %s completato: email inviata e storico salvato", self._trip_id)

        except Exception as exc:
            logger.exception("trip %s fallito", self._trip_id)
            await self._store.update_status(self._trip_id, TripStatus.ERROR, result=str(exc))

    async def _save_history(self, trip: TripResponse, email_content: dict, body_text: str, package: dict) -> None:
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
            email_body=body_text,
            package=package,
        )

    async def _send_email(self, trip: TripResponse, email_content: dict, body_text: str, body_html: str) -> None:
        await self._email.send(
            to=trip.email, subject=email_content["subject"], body=body_text, html=body_html
        )

    @staticmethod
    def _compose_body_text(email_content: dict) -> str:
        lines = [email_content["opening"], "", email_content["understanding"], "", "Ecco tre punti di partenza concreti:"]
        for i, item in enumerate(email_content["resources"], 1):
            parts = [f"{i}. {item['name']}"]
            if item.get("price"):
                parts.append(f"   {item['price']}")
            if item.get("description"):
                parts.append(f"   {item['description']}")
            parts.append(f"   {item['link']}")
            lines.append("\n".join(parts))
        lines.append("")
        lines.append(email_content["honest_note"])
        lines.append("")
        lines.append("Buon ritorno a casa,")
        lines.append("Edoardo & Chiara")
        lines.append("Nostos")
        return "\n".join(lines)


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

        prompt = f"""Sei Xen-IA, un'assistente AI che aiuta a comporre viaggi autentici, lontani dal
        turismo di massa. Devi scrivere un'email a una persona che ha appena raccontato il viaggio
        che sogna.

        STRUTTURA OBBLIGATORIA dell'email (in campi separati):
        1) opening: 2-3 frasi (~50 parole), frase d'attacco non banale che aggancia subito il
           lettore. NON presentarti come Xen-IA qui.
        2) understanding: 2-3 frasi che dimostrano di aver capito davvero cosa cerca il
           viaggiatore — riprendi interessi, stile e ritmo della richiesta, con tono discorsivo
           e un po' prolisso, per creare vicinanza.
        3) resources: TRE voci (dalle risorse sotto), ciascuna presa PAROLA PER PAROLA dai dati
           reali (nome, prezzo, link). Niente di inventato.
        4) honest_note: 1-2 frasi che accennano che l'email è stata preparata con il supporto di
           un assistente AI (senza ripetere il nome Xen-IA), ricordano che prezzi/date vanno
           verificati, e invitano a rispondere per ragionarci insieme.

        REGOLE:
        - Scrivere in italiano, TESTO PIANO: niente markdown, asterischi, trattini o hashtag
          dentro i campi.
        - Usa esclusivamente le risorse elencate sotto; se una categoria è vuota, non forzarla e
          non inventare nulla.
        - opening + understanding + honest_note più ampi; resources stringati.
        - Firma NON inclusa nei campi: viene aggiunta dal sistema.

        CONTESTO VIAGGIO:
        Interessi: {', '.join(intent.interests) or 'non specificati'}
        Stile ricercato: {', '.join(intent.style) or 'non specificato'}
        Ritmo: {intent.pace or 'non specificato'}

        RISORSE CONSULTABILI (usa queste):
        Voli:
        {self._render_flights(flights_list)}

        Punti di interesse:
        {self._render_maps(maps_list)}

        Alloggi:
        {self._render_places(places_list)}
        """
        email_content = await self._llm.extract_json(prompt, EMAIL_CONTENT_SCHEMA)

        body_text = self._compose_body_text(email_content)
        body_html = build_html_email(email_content)
        return email_content, body_text, body_html, package

    @staticmethod
    def _render_flights(items: list[dict]) -> str:
        if not items:
            return "nessun volo disponibile"
        return "\n".join(
            f"{i}. {it.get('airline')}, {it.get('from')} -> {it.get('to')}, "
            f"partenza {it.get('departure_date')}, {it.get('price_eur')} EUR — {it.get('link')}"
            for i, it in enumerate(items, 1)
        )

    @staticmethod
    def _render_maps(items: list[dict]) -> str:
        if not items:
            return "nessun punto di interesse"
        return "\n".join(
            f"{i}. {it.get('name')} ({it.get('type')}, {it.get('rating')} stelle) — {it.get('link')}"
            for i, it in enumerate(items, 1)
        )

    @staticmethod
    def _render_places(items: list[dict]) -> str:
        if not items:
            return "nessun alloggio"
        return "\n".join(
            f"{i}. {it.get('name')} — {it.get('price_per_night_eur')} EUR/notte — {it.get('link')}"
            for i, it in enumerate(items, 1)
        )