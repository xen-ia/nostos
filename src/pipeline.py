import asyncio
import logging
import time
from contextlib import asynccontextmanager

from src.apis.llm import LLMClient
from src.trip_store import TripResponse, TripStatus, TripStore
from src.tools import flights, maps, places
from src.apis.email import EmailSender, build_html_email
from src.database import Database
from src.models import EmailContent, TripIntent
from src.prompts import build_email_prompt, build_intent_prompt

logger = logging.getLogger("nostos.pipeline")

HONEST_NOTE = "Questa email è generata automaticamente con Xen-IA, assistente AI di Nostos."

CTA = "Se la proposta ti incuriosisce, questo è solo l'inizio: c'è molto altro di cui parlare. Continuiamo insieme."


class NoResourcesError(RuntimeError):
    """All SerpAPI searches are empty or timed out: trip aborted without sending the email."""


class TripOrchestrator:
    LOCK_TTL_SECONDS = 300

    @asynccontextmanager
    async def _timed(self, label: str):
        start = time.monotonic()
        try:
            yield
        finally:
            logger.info("%s: %.1fs", label, time.monotonic() - start)

    def __init__(
        self,
        store: TripStore,
        llm_client: LLMClient,
        email_sender: EmailSender,
        database: Database,
        trip_id: str,
        serpapi_timeout: float = 60.0,
        email_timeout: float = 60.0,
    ):
        self._store = store
        self._llm = llm_client
        self._email = email_sender
        self._db = database
        self._trip_id = trip_id
        self._serpapi_timeout = serpapi_timeout
        self._email_timeout = email_timeout

    async def run(self) -> None:
        claimed = await self._store.claim(self._trip_id, ttl_seconds=self.LOCK_TTL_SECONDS)
        if not claimed:
            return

        try:
            trip = await self._store.get(self._trip_id)
            await self._store.update_status(self._trip_id, TripStatus.RUNNING)

            intent = await self._extract_intent(trip)
            logger.info("intent extracted: %s", intent.model_dump())

            async with self._timed("compose_package"):
                email_content, body_text, body_html, package = await self._compose_package(trip, intent)

            async with self._timed("send_email"):
                await self._send_email(trip, email_content, body_text, body_html)
            async with self._timed("save_history"):
                await self._save_history(trip, email_content, body_text, package)
            logger.info("trip %s completed: email sent and history saved", self._trip_id)

        except Exception as exc:
            logger.exception("trip %s failed", self._trip_id)
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
            to=trip.email,
            subject=email_content["subject"],
            body=body_text,
            html=body_html,
            timeout=self._email_timeout,
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
        lines.append(email_content["cta"])
        lines.append("")
        lines.append(email_content["honest_note"])
        lines.append("")
        lines.append("Buon ritorno a casa,")
        lines.append("Edoardo & Chiara")
        lines.append("CEOs@Nostos")
        return "\n".join(lines)


    async def _extract_intent(self, trip: TripResponse) -> TripIntent:
        prompt = build_intent_prompt(trip)
        async with self._timed("extract_intent (LLM)"):
            return await self._llm.extract(prompt, TripIntent)

    async def _compose_package(self, trip: TripResponse, intent: TripIntent) -> tuple[dict, dict]:
        destination = intent.destination or trip.destination
        departure_code = intent.departure_airport_code or trip.departure_location
        destination_code = intent.destination_airport_code or destination
        async with self._timed("serpapi (flights+maps+places)"):
            results = await asyncio.gather(
                flights.search(departure_code, destination_code, trip.start_date, trip.end_date, timeout=self._serpapi_timeout),
                maps.research(destination, intent.interests, timeout=self._serpapi_timeout),
                places.search(destination, intent.interests, intent.style, trip.start_date, trip.end_date, timeout=self._serpapi_timeout),
                return_exceptions=True,
            )
        flights_list, maps_list, places_list = (r if not isinstance(r, Exception) else [] for r in results)

        for label, result in (("flights", results[0]), ("pois", results[1]), ("stays", results[2])):
            if isinstance(result, Exception):
                logger.warning("%s: error %s", label, type(result).__name__)
            else:
                logger.info("%s: %d results", label, len(result))

        if not flights_list and not maps_list and not places_list:
            logger.warning(
                "trip %s: no SerpAPI resources (flights=%d, pois=%d, stays=%d) — trip aborted without email",
                self._trip_id,
                len(flights_list),
                len(maps_list),
                len(places_list),
            )
            raise NoResourcesError(
                "No resources retrieved from SerpAPI (all searches empty or timed out): "
                "email not sent"
            )

        package = {
            "intent": intent.model_dump(),
            "flights": flights_list[:3],
            "maps": maps_list[:3],
            "places": places_list[:3],
        }

        prompt = build_email_prompt(
            intent,
            self._render_flights(flights_list),
            self._render_maps(maps_list),
            self._render_places(places_list),
        )
        async with self._timed("compose_email (LLM)"):
            content = await self._llm.extract(prompt, EmailContent)
        email_content = content.model_dump()
        email_content["honest_note"] = HONEST_NOTE
        email_content["cta"] = CTA

        body_text = self._compose_body_text(email_content)
        body_html = build_html_email(email_content)
        return email_content, body_text, body_html, package

    @staticmethod
    def _render_flights(items: list[dict]) -> str:
        if not items:
            return "no flights available"
        return "\n".join(
            f"{i}. {it.get('airline')}, {it.get('from')} -> {it.get('to')}, "
            f"departure {it.get('departure_date')}, {it.get('price_eur')} EUR — {it.get('link')}"
            for i, it in enumerate(items, 1)
        )

    @staticmethod
    def _render_maps(items: list[dict]) -> str:
        if not items:
            return "no points of interest"
        return "\n".join(
            f"{i}. {it.get('name')} ({it.get('type')}, {it.get('rating')} stars) — {it.get('link')}"
            for i, it in enumerate(items, 1)
        )

    @staticmethod
    def _render_places(items: list[dict]) -> str:
        if not items:
            return "no accommodations available"
        return "\n".join(
            f"{i}. {it.get('name')} — {it.get('price_per_night_eur')} EUR/night — {it.get('link')}"
            for i, it in enumerate(items, 1)
        )