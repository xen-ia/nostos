"""TripOrchestrator: end-to-end trip pipeline (intent -> research -> email)."""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

from src.services.apis.llm import LLMClient
from src.services.trip_store import TripResponse, TripStatus, TripStore
from src.services.tools import dedupe_cap, flights, maps, places
from src.services.tools.flights import IATA_PATTERN
from src.services.apis.email import (
    SIGNATURE_GREETING,
    SIGNATURE_NAME,
    SIGNATURE_ROLE,
    EmailSender,
    build_html_email,
)
from src.infrastructure.database import Database
from src.core.models import (
    Curation,
    DepartureAirports,
    EmailContent,
    PeriodPlan,
    ResolvedDestinations,
    TargetQueries,
    TripIntent,
)
from src.core.prompts import (
    build_curation_prompt,
    build_email_prompt,
    build_geo_prompt,
    build_intent_prompt,
    build_period_prompt,
    build_target_prompt,
)
from src.core.validation import build_allowed_resources, sanitize_windows, validate_resources

logger = logging.getLogger("nostos.orchestrator")

MAX_WINDOWS = 2
MAX_TARGET_QUERIES = 4
CORPUS_CAP = 8
MAX_FLIGHT_PROBES = 8
MAX_DEPARTURE_AIRPORTS = 4
MAX_RESOLVED_DESTINATIONS = 2
FLEXIBLE_WINDOW_SHIFT_DAYS = 7
FLIGHT_BLOCKING_TRAVEL_MODES = frozenset({"auto", "van", "treno"})

HONEST_NOTE = "Questa email è generata automaticamente con Xen-IA, assistente AI di Nostos."

CTA = "Se questa direzione ti somiglia, rispondi a questa email: costruiamo insieme il resto del viaggio."


def _valid_iata(codes) -> list[str]:
    """Keeps only well-formed IATA codes: raw strings must never reach google_flights."""
    out: list[str] = []
    for code in codes:
        cleaned = (code or "").strip().upper()
        if cleaned and IATA_PATTERN.fullmatch(cleaned) and cleaned not in out:
            out.append(cleaned)
    return out


class NoResourcesError(RuntimeError):
    """All SerpAPI searches are empty or timed out: trip aborted without sending the email."""


class TripOrchestrator:
    LOCK_TTL_SECONDS = 300
    LOCK_RENEW_INTERVAL_SECONDS = 60

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
        serpapi_api_key: str | None = None,
        llm_model: str | None = None,
        app_version: str | None = None,
    ):
        self._store = store
        self._llm = llm_client
        self._email = email_sender
        self._db = database
        self._trip_id = trip_id
        self._serpapi_timeout = serpapi_timeout
        self._email_timeout = email_timeout
        self._serpapi_api_key = serpapi_api_key
        self._llm_model = llm_model
        self._app_version = app_version

    async def _renew_lease(self) -> None:
        while True:
            await asyncio.sleep(self.LOCK_RENEW_INTERVAL_SECONDS)
            await self._store.renew(self._trip_id, self.LOCK_TTL_SECONDS)

    async def run(self) -> None:
        claimed = await self._store.claim(self._trip_id, ttl_seconds=self.LOCK_TTL_SECONDS)
        if not claimed:
            return

        renewer = asyncio.create_task(self._renew_lease())
        started_at = time.monotonic()

        try:
            trip = await self._store.get(self._trip_id)
            await self._store.update_status(self._trip_id, TripStatus.RUNNING)

            intent = await self._extract_intent(trip)
            logger.info("intent extracted for trip %s", self._trip_id)

            async with self._timed("research"):
                windows = await self._plan_period(trip, intent)
                resolved, departure_codes = await self._geo_plan(trip, intent)
                tool_calls: list[dict] = []
                destination = self._effective_destination(trip, intent, resolved)
                anchors = await self._explore(destination, tool_calls)
                targeted = await self._target(trip, intent, anchors)
                research = await self._execute_searches(
                    trip, intent, targeted, windows, anchors, tool_calls,
                    resolved=resolved, departure_codes=departure_codes,
                )

            async with self._timed("curate+compose"):
                curated = await self._curate(trip, intent, research["corpus"])
                research["curated"] = curated
                email_content, body_text, body_html, package = await self._compose_email(trip, intent, research)

            async with self._timed("save_history"):
                await self._save_history(trip, email_content, body_text, package)

            async with self._timed("send_email"):
                await self._send_email(trip, email_content, body_text, body_html)
            await self._store.update_status(self._trip_id, TripStatus.DONE)
            await self._db.update_status(
                self._trip_id,
                TripStatus.DONE.value,
                send_datetime=datetime.now(timezone.utc),
                duration_seconds=round(time.monotonic() - started_at, 3),
            )
            logger.info("trip %s completed: email sent and history saved", self._trip_id)

        except Exception as exc:
            logger.exception("trip %s failed", self._trip_id)
            await self._store.update_status(self._trip_id, TripStatus.ERROR, result=str(exc))
            await self._db.update_status(
                self._trip_id,
                TripStatus.ERROR.value,
                error_message=str(exc),
                duration_seconds=round(time.monotonic() - started_at, 3),
            )
        finally:
            renewer.cancel()
            await self._store.release(self._trip_id)

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
            departure_location=trip.departure_location,
            free_text=trip.free_text,
            email_subject=email_content["subject"],
            email_body=body_text,
            package=package,
            model=self._llm_model,
            version=self._app_version,
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
        lines = [email_content["opening"], "", email_content["understanding"], "", "Ecco i punti di partenza:"]
        for i, item in enumerate(email_content["resources"], 1):
            parts = [f"{i}. {item['name']}"]
            if item.get("price"):
                parts.append(f"   {item['price']}")
            if item.get("description"):
                parts.append(f"   {item['description']}")
            parts.append(f"   {item['link']}")
            lines.append("\n".join(parts))
        appendix = email_content.get("appendix", {})
        if appendix:
            lines.append("")
            lines.append("Fonti esplorate:")
            for label, items in appendix.get("groups", []):
                named = [i for i in items if i.get("link")]
                if named:
                    lines.append(f"{label}: " + "; ".join(f"{i.get('name') or i['link']} {i['link']}" for i in named))
            for url in appendix.get("source_links", []):
                lines.append(f"Ricerca voli: {url}")
        lines.append("")
        lines.append(email_content["cta"])
        lines.append("")
        lines.append(email_content["honest_note"])
        lines.append("")
        lines.append(SIGNATURE_GREETING)
        lines.append(SIGNATURE_NAME)
        lines.append(SIGNATURE_ROLE)
        return "\n".join(lines)


    async def _extract_intent(self, trip: TripResponse) -> TripIntent:
        prompt = build_intent_prompt(trip)
        async with self._timed("extract_intent (LLM)"):
            return await self._llm.extract(prompt, TripIntent)

    async def _plan_period(
        self, trip: TripResponse, intent: TripIntent
    ) -> list[tuple[str, str | None]]:
        if trip.start_date and trip.end_date:
            return [(trip.start_date, trip.end_date)]
        if trip.start_date:
            return [(trip.start_date, None)]
        prompt = build_period_prompt(trip, intent, date.today().isoformat())
        plan = await self._llm.extract(prompt, PeriodPlan)
        windows = sanitize_windows([w.model_dump() for w in plan.windows], date.today())
        logger.info("period plan: %d usable window(s)", len(windows))
        return windows[:MAX_WINDOWS]

    async def _geo_plan(self, trip: TripResponse, intent: TripIntent) -> tuple[ResolvedDestinations, list[str]]:
        """RESOLVE + DEPARTURES expansion (spec C1/C2).

        Both extract() calls share the SAME build_geo_prompt text — one call per schema
        keeps a single model per extraction while the context stays identical.
        """
        prompt = build_geo_prompt(trip, intent)
        async with self._timed("geo_plan (LLM)"):
            resolved = await self._llm.extract(prompt, ResolvedDestinations)
            airports = await self._llm.extract(prompt, DepartureAirports)
        destinations = resolved.destinations[:MAX_RESOLVED_DESTINATIONS]
        codes = _valid_iata(airports.codes)[:MAX_DEPARTURE_AIRPORTS]
        logger.info(
            "geo plan: %d resolved destination(s) [%s], %d departure code(s)",
            len(destinations), "; ".join(p.name for p in destinations), len(codes),
        )
        return ResolvedDestinations(destinations=destinations, rationale=resolved.rationale), codes

    @staticmethod
    def _effective_destination(trip: TripResponse, intent: TripIntent, resolved: ResolvedDestinations) -> str | None:
        return (
            " e ".join(p.name for p in resolved.destinations)
            or intent.destination
            or trip.destination
        )

    @staticmethod
    def _flight_windows(trip: TripResponse, planned: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
        """Spec C3/D2: absent dates -> period-plan windows; hard dates -> exactly the given
        window; flexible dates -> given plus start±FLEXIBLE_WINDOW_SHIFT_DAYS, deduped."""
        if not trip.start_date:
            return planned
        base = (trip.start_date, trip.end_date)
        if not trip.flexible_dates:
            return [base]
        start = date.fromisoformat(trip.start_date)
        end = date.fromisoformat(trip.end_date) if trip.end_date else None
        windows = [base]
        for delta in (-FLEXIBLE_WINDOW_SHIFT_DAYS, FLEXIBLE_WINDOW_SHIFT_DAYS):
            candidate = (
                (start + timedelta(days=delta)).isoformat(),
                ((end + timedelta(days=delta)).isoformat() if end else None),
            )
            if candidate not in windows:
                windows.append(candidate)
        return windows[:3]

    async def _explore(self, destination: str | None, tool_calls: list[dict]) -> list[dict]:
        if not destination:
            return []
        query = f"quartieri e luoghi chiave in {destination}"
        try:
            anchors = await maps.research(query, timeout=self._serpapi_timeout, api_key=self._serpapi_api_key)
        except Exception as exc:  # noqa: BLE001 — exploration must never abort the trip
            logger.warning("google_maps explore: error %s: %s", type(exc).__name__, exc)
            return []
        self._log_call(tool_calls, "google_maps", {"q": query}, anchors)
        return anchors

    async def _target(self, trip: TripResponse, intent: TripIntent, anchors: list[dict]) -> list[str]:
        if not anchors:
            return []
        anchors_block = "\n".join(
            f"- {a.get('name')} ({a.get('type')}) {a.get('address') or ''}".strip() for a in anchors[:CORPUS_CAP]
        )
        plan = await self._llm.extract(build_target_prompt(trip, intent, anchors_block), TargetQueries)
        return [q.query for q in plan.queries][:MAX_TARGET_QUERIES]

    def _log_call(self, tool_calls: list[dict], engine: str, params: dict, results: list[dict]) -> None:
        tool_calls.append({"engine": engine, "params": params, "result_count": len(results)})
        logger.info("%s: %d results (%s)", engine, len(results), params.get("q") or params.get("departure_id"))

    async def _execute_searches(
        self,
        trip: TripResponse,
        intent: TripIntent,
        targeted_queries: list[str],
        windows: list[tuple[str, str | None]],
        anchors: list[dict],
        tool_calls: list[dict],
        resolved: ResolvedDestinations,
        departure_codes: list[str],
    ) -> dict:
        destination = self._effective_destination(trip, intent, resolved)
        errors: list[Exception] = []

        async def guarded(coro, engine: str, params: dict) -> list[dict]:
            try:
                res = await coro
            except Exception as exc:  # noqa: BLE001 — mirrored from previous behavior
                errors.append(exc)
                logger.warning("%s: error %s: %s", engine, type(exc).__name__, exc)
                return []
            self._log_call(tool_calls, engine, params, res)
            return res

        maps_results = await asyncio.gather(*(
            guarded(maps.research(q, timeout=self._serpapi_timeout, api_key=self._serpapi_api_key),
                    "google_maps", {"q": q})
            for q in targeted_queries
        ))

        # Flight matrix (spec C3): gates first, then capped prioritized probes.
        if trip.travel_mode in FLIGHT_BLOCKING_TRAVEL_MODES:
            skipped_reason = f"travel_mode:{trip.travel_mode}"
        else:
            departures = departure_codes or _valid_iata([intent.departure_airport_code])
            arrivals = (
                _valid_iata([p.airport_code for p in resolved.destinations])
                or _valid_iata([intent.destination_airport_code])
            )
            if not departures or not arrivals:
                skipped_reason = "no_airports"
            else:
                skipped_reason = None

        flight_windows = self._flight_windows(trip, windows)

        async def probe(combo: tuple[tuple[str, str | None], str, str]):
            window, arrival, departure = combo
            params = {"departure_id": departure, "arrival_id": arrival,
                      "outbound_date": window[0], "return_date": window[1]}
            res = await guarded(flights.search(departure, arrival, window[0], window[1],
                                               timeout=self._serpapi_timeout, api_key=self._serpapi_api_key),
                                "google_flights", params)
            return combo, res

        if skipped_reason:
            tool_calls.append({"engine": "google_flights", "skipped": True, "reason": skipped_reason})
            probed: list[tuple[tuple[str, str | None], str, str, list[dict]]] = []
        else:
            combos = self._build_flight_combos(flight_windows, arrivals[:2], departures[:3])
            probed = await asyncio.gather(*(probe(c) for c in combos))

        candidates = [(c, f) for c, fs in probed for f in fs]
        sources: list[str] = []
        for _, f in candidates:
            url = f.get("link")
            if url and url not in sources:
                sources.append(url)

        best = min(
            candidates,
            key=lambda cf: cf[1].get("price_eur") if cf[1].get("price_eur") is not None else float("inf"),
            default=None,
        )
        flights_list = [best[1]] if best else []
        winning_window = best[0][0] if best else (flight_windows[0] if flight_windows else (trip.start_date, trip.end_date))

        check_in = trip.start_date or winning_window[0]
        check_out = trip.end_date or winning_window[1]
        stay_preference = trip.stay_preference
        places_query = (
            f"{stay_preference} stays in {destination}"
            if stay_preference not in (None, "indifferente") and destination
            else f"hotels in {destination}"
        )
        stays = await guarded(
            places.search(destination=destination, query=places_query, check_in_date=check_in, check_out_date=check_out,
                          timeout=self._serpapi_timeout, api_key=self._serpapi_api_key),
            "google_hotels", {"q": places_query, "check_in_date": check_in, "check_out_date": check_out},
        )

        maps_items = [*anchors, *(i for lst in maps_results for i in lst)]
        linked_maps = [i for i in maps_items if i.get("link")]
        linkless_names = [i.get("name") for i in maps_items if not i.get("link")]
        if linkless_names:
            logger.warning("maps corpus: dropped %d link-less entries: %s", len(linkless_names), linkless_names)

        corpus = {
            "flights": [{k: v for k, v in f.items() if k != "_meta"} for f in flights_list],
            "maps": dedupe_cap(linked_maps, cap=CORPUS_CAP),
            "places": stays,
        }
        geo_block = {
            "resolved": [p.model_dump() for p in resolved.destinations],
            "departure_codes": departure_codes or _valid_iata([intent.departure_airport_code]),
            "skipped_flights_reason": skipped_reason,
            "resolve_rationale": resolved.rationale,
        }
        if not any(corpus.values()):
            if errors:
                raise NoResourcesError("No resources retrieved from SerpAPI (all searches failed): email not sent")
            logger.warning(
                "trip %s: no SerpAPI resources (flights=%d, pois=%d, stays=%d) — trip aborted without email",
                self._trip_id,
                len(corpus["flights"]),
                len(corpus["maps"]),
                len(corpus["places"]),
            )
            raise NoResourcesError("No resources retrieved from SerpAPI (all searches empty): email not sent")
        return {
            "corpus": corpus,
            "tool_calls": tool_calls,
            "sources": sources,
            "winning_window": winning_window,
            "geo": geo_block,
        }

    @staticmethod
    def _build_flight_combos(
        windows: list[tuple[str, str | None]], arrivals: list[str], departures: list[str]
    ) -> list[tuple[tuple[str, str | None], str, str]]:
        """Spec C3 priority when capping: cover ALL windows first, then arrivals, then
        departures — extra departures are never spent before every window is probed."""
        if not windows or not arrivals or not departures:
            return []
        pairs = [(arrivals[0], departures[0])]
        pairs.extend((a, departures[0]) for a in arrivals[1:])
        pairs.extend((arrivals[0], d) for d in departures[1:])
        combos = [(w, a, d) for a, d in pairs for w in windows]
        return combos[:MAX_FLIGHT_PROBES]

    @staticmethod
    def _render_numbered(items: list[dict], prefix: str) -> str:
        if not items:
            return "none available"
        return "\n".join(f"[{prefix}{i}] {it.get('name')} — {it.get('link')}" for i, it in enumerate(items))

    async def _curate(self, trip: TripResponse, intent: TripIntent, corpus: dict) -> dict:
        blocks = (
            f"Flights:\n{self._render_numbered(corpus['flights'], 'F')}\n\n"
            f"Points of interest:\n{self._render_numbered(corpus['maps'], 'M')}\n\n"
            f"Accommodation:\n{self._render_numbered(corpus['places'], 'P')}"
        )
        cur = await self._llm.extract(build_curation_prompt(trip, intent, blocks), Curation)

        def pick(indices: list[int], items: list[dict]) -> list[dict]:
            out = []
            for idx in indices:
                if 0 <= idx < len(items):
                    out.append(items[idx])
                else:
                    logger.warning("curation index %d out of range (0..%d) — dropped", idx, len(items) - 1)
            return out[:3]

        curated = {
            "flights": pick(cur.flight_indices, corpus["flights"]),
            "maps": pick(cur.poi_indices, corpus["maps"]),
            "places": pick(cur.stay_indices, corpus["places"]),
        }
        if not any(curated.values()):
            # merit fallback: keep corpus top items rather than aborting a researched trip
            curated = {k: v[:3] for k, v in corpus.items()}
        return curated

    async def _compose_email(
        self, trip: TripResponse, intent: TripIntent, research: dict
    ) -> tuple[dict, str, str, dict]:
        corpus, curated = research["corpus"], research["curated"]
        allowed = build_allowed_resources(curated["flights"], curated["maps"], curated["places"])

        resolve_rationale = research.get("geo", {}).get("resolve_rationale", "")
        prompt = build_email_prompt(intent,
                                    self._render_flights(curated["flights"], numbered=True),
                                    self._render_maps(curated["maps"], numbered=True),
                                    self._render_places(curated["places"], numbered=True),
                                    trip,
                                    resolve_rationale=resolve_rationale)
        content = (await self._llm.extract(prompt, EmailContent)).model_dump()

        report = validate_resources(content["resources"], allowed)
        if report.invalid or not content["resources"]:
            logger.warning("invalid resources dropped: %s", [r.get("name") for r in report.invalid])
            content["resources"] = report.valid
            if not content["resources"]:
                retry_prompt = prompt + "\n\nIMPORTANT: your previous answer cited resources not in the list and was rejected. Use ONLY the listed resources."
                content = (await self._llm.extract(retry_prompt, EmailContent)).model_dump()
                report = validate_resources(content["resources"], allowed)
                content["resources"] = report.valid
                if not content["resources"]:
                    raise NoResourcesError("email composition could not ground any real resource")

        content["honest_note"] = HONEST_NOTE
        content["cta"] = CTA
        content["sections_map"] = {
            "flights": [r["link"] for r in curated["flights"] if r.get("link")],
            "places": [r["link"] for r in curated["places"] if r.get("link")],
            "maps": [r["link"] for r in curated["maps"] if r.get("link")],
        }
        content["appendix"] = self._build_appendix(research)
        body_text = self._compose_body_text(content)
        body_html = build_html_email(content)
        package = {
            "intent": intent.model_dump(),
            "geo": research.get("geo", {}),
            "corpus": corpus,
            "curated": curated,
            "tool_calls": research["tool_calls"],
        }
        return content, body_text, body_html, package

    @staticmethod
    def _build_appendix(research: dict) -> dict:
        corpus = research["corpus"]

        def brief_items(items: list[dict]) -> list[dict]:
            return [
                {"name": it.get("name") or it.get("airline"), "link": it.get("link")}
                for it in items
            ]

        return {
            "groups": [
                ("Voli", brief_items(corpus["flights"])),
                ("Dove stare", brief_items(corpus["places"])),
                ("Cosa fare", brief_items(corpus["maps"])),
            ],
            "source_links": research.get("sources", []),
        }

    @staticmethod
    def _render_flights(items: list[dict], numbered: bool = False) -> str:
        if not items:
            return "no flights available"

        def label(i: int) -> str:
            return f"[F{i}] " if numbered else ""

        return "\n".join(
            f"{label(i)}{it.get('airline')}, {it.get('from')} -> {it.get('to')}, "
            f"departure {it.get('departure_date')}, {it.get('price_eur')} EUR — {it.get('link')}"
            for i, it in enumerate(items)
        )

    @staticmethod
    def _render_maps(items: list[dict], numbered: bool = False) -> str:
        if not items:
            return "no points of interest"

        def label(i: int) -> str:
            return f"[M{i}] " if numbered else ""

        return "\n".join(
            f"{label(i)}{it.get('name')} ({it.get('type')}, {it.get('rating')} stars) — {it.get('link')}"
            for i, it in enumerate(items)
        )

    @staticmethod
    def _render_places(items: list[dict], numbered: bool = False) -> str:
        if not items:
            return "no accommodations available"

        def label(i: int) -> str:
            return f"[P{i}] " if numbered else ""

        return "\n".join(
            f"{label(i)}{it.get('name')} — {it.get('price_per_night_eur')} EUR/night — {it.get('link')}"
            for i, it in enumerate(items)
        )
