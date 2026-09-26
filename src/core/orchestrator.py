"""TripOrchestrator: end-to-end trip pipeline (intent -> research -> email)."""
import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus, urlparse

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
    TripPlan,
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
from src.core.decision_router import route_trip
from src.core.decision_scoring import pick_best_flight, pick_top_pois
from src.services.apis.decisions import build_decision_client
from src.settings import get_settings

logger = logging.getLogger("nostos.orchestrator")

MAX_WINDOWS = 2
MAX_TARGET_QUERIES = 4
CORPUS_CAP = 8
MAX_FLIGHT_PROBES = 12
MAX_DEPARTURE_AIRPORTS = 4
MAX_RESOLVED_DESTINATIONS = 2
FLEXIBLE_WINDOW_SHIFT_DAYS = 7


HONEST_NOTE = "Questa email è generata automaticamente con Xen-IA, assistente AI di Nostos."

CTA = "Com'è andata? Lasciaci un feedback."

JUNK_DOMAINS = frozenset({
    "facebook.com", "instagram.com", "tiktok.com", "twitter.com", "x.com",
    "youtube.com", "youtu.be",
})

#: Numbered-corpus IDs (e.g. [F0], [M12], [P3]) the LLM echoes into EmailContent
#: text fields. Stripped post-validation in _compose_email; the ID plus at most
#: one adjacent space goes, preferring the trailing one ("[F0] X" -> "X").
_BRACKET_ID_RE = re.compile(r"\[(?:F|M|P)\d+\] ?| ?\[(?:F|M|P)\d+\]")


def _strip_bracket_id(text: str | None) -> str:
    """Remove leaked corpus IDs from a single text field."""
    return _BRACKET_ID_RE.sub("", text or "").strip()


def strip_bracket_ids(content: dict) -> dict:
    """Remove leaked corpus IDs from opening/understanding and every resource
    name/description/price. Runs after validation (IDs never affect grounding)
    and before rendering, so both HTML and text builders receive clean copy."""
    for field in ("opening", "understanding"):
        if content.get(field):
            content[field] = _strip_bracket_id(content[field])
    for resource in content.get("resources", []):
        for field in ("name", "description", "price"):
            if resource.get(field):
                resource[field] = _strip_bracket_id(resource[field])
    return content


def _is_junk_link(link: str | None) -> bool:
    """True for social/video links that must never reach an email."""
    if not link:
        return False
    try:
        host = urlparse(link).netloc.lower().split(":")[0]
    except ValueError:
        return False
    return host == "x.com" or any(
        host == d or host.endswith("." + d) for d in JUNK_DOMAINS if d != "x.com"
    )


def _maps_search_link(name: str | None, address: str | None) -> str | None:
    """Universal Google Maps link for a link-less place. None when no name."""
    if not (name or "").strip():
        return None
    query = name.strip() + (f" {address.strip()}" if (address or "").strip() else "")
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(query)


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

            decision_client = build_decision_client(get_settings())
            jev_route = None
            tool_calls_jev = None
            if decision_client is not None:
                try:
                    jev_route = await route_trip(trip, decision_client)
                    tool_calls_jev = {"engine": "jev-router", "model": jev_route.get("model", ""), "decisions": jev_route["decisions"], "bands": jev_route["bands"]}
                except Exception:
                    logger.warning("jev route failed, falling back to LLM path", exc_info=True)
                    jev_route = None
                    tool_calls_jev = None
                finally:
                    close = getattr(decision_client, "close", None) or getattr(decision_client, "aclose", None)
                    if callable(close):
                        try:
                            await close()
                        except Exception:
                            logger.debug("jev client close failed", exc_info=True)

            intent = await self._extract_intent(trip)
            logger.info("intent extracted for trip %s", self._trip_id)

            jev_decisions = (jev_route or {}).get("decisions", {}) or {}
            jev_bands = (jev_route or {}).get("bands", {}) or {}
            jev_active = (
                jev_route is not None
                and tool_calls_jev is not None
                and not (jev_bands.get("travel_mode") == "fallback"
                         and jev_bands.get("needs_flights") == "fallback")
            )
            if jev_active:
                logger.info("jev route active for trip %s: %s", self._trip_id, jev_decisions)

            # Jev overrides apply to research queries only: email composition keeps
            # the LLM intent (allow-list validation + template unchanged).
            search_intent = intent
            if jev_active:
                overrides: dict = {}
                jev_travel_mode = jev_decisions.get("travel_mode")
                if isinstance(jev_travel_mode, str) and jev_travel_mode:
                    overrides["travel_mode"] = jev_travel_mode
                jev_needs_flights = jev_decisions.get("needs_flights")
                if isinstance(jev_needs_flights, bool):
                    overrides["needs_flights"] = jev_needs_flights
                if overrides:
                    search_intent = intent.model_copy(update=overrides)

            async with self._timed("research"):
                windows = await self._plan_period(trip, intent)
                resolved, departure_codes = await self._geo_plan(trip, intent)
                tool_calls: list[dict] = []
                destination = self._effective_destination(trip, intent, resolved)
                anchors = await self._explore(destination, tool_calls, resolved=resolved)
                targeted = await self._target(trip, intent, anchors)
                research = await self._execute_searches(
                    trip, search_intent, targeted, windows, anchors, tool_calls,
                    resolved=resolved, departure_codes=departure_codes,
                )
                if jev_active and tool_calls_jev is not None:
                    self._apply_jev_scores(research, jev_decisions)
                    research["tool_calls"].append(tool_calls_jev)

            async with self._timed("curate+compose"):
                curated = await self._curate(trip, intent, research["corpus"])
                if not curated["maps"] and not curated["places"]:
                    raise NoResourcesError(
                        "only a flight was found: not enough for a useful email, trip aborted without sending"
                    )
                research["curated"] = curated
                trip_plan = await self._plan_itinerary(trip, intent, curated)
                research["trip_plan"] = trip_plan
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
        lines = [email_content["opening"], "", email_content["understanding"], ""]
        smap = email_content.get("sections_map", {})
        flight_links = set(smap.get("flights", []))
        resources = email_content.get("resources", [])
        flight_items = [r for r in resources if r.get("link") in flight_links]
        hero_link = next((r["link"] for r in flight_items if r.get("link")), None)
        if flight_items:
            lines.append("Come arrivare:")
            first = flight_items[0]
            flight_line = first["name"]
            if first.get("price"):
                flight_line += f" — {first['price']}"
            lines.append(flight_line)
            lines.append(first["link"])
            lines.append("")
        # Travel mode labels/descriptions mirror the HTML travel box one-liners.
        travel_mode = email_content.get("travel_mode")
        travel_mode_lower = travel_mode.lower() if isinstance(travel_mode, str) else ""
        is_van = travel_mode_lower == "van_life" or (email_content.get("accommodation_style") or "").lower() == "van"
        base_listed = [r for r in resources if r.get("link") != hero_link] if hero_link else list(resources)
        place_links = set(smap.get("places", []))
        rentals = [r for r in base_listed
                   if r.get("rental") and r.get("link") in place_links][:2] if is_van else []
        rental_links = {r.get("link") for r in rentals}
        lines.append("Punti di partenza:")
        listed = [r for r in base_listed if r.get("link") not in rental_links]
        for i, item in enumerate(listed, 1):
            entry = f"{i}. {item['name']}"
            if item.get("price"):
                entry += f" — {item['price']}"
            lines.append(entry)
            if item.get("description"):
                lines.append(f"   {item['description']}")
            lines.append(f"   {item['link']}")

        # Travel box one-liner mirroring the HTML hierarchy (no Mezzi line:
        # mobility info lives in the LLM prose, a bare vehicle list makes no sense).
        # Neutral one-liners only: specifics come from grounded resource text.
        mode_labels = {
            "road_trip": "Come muoversi in loco",
            "van_life": "Vita in van",
            "sailing": "Navigazione",
        }
        mode_descriptions = {
            "road_trip": "Tappe giornaliere in auto, strada facendo.",
            "van_life": "Itinerario su strada, pernottamenti a bordo.",
            "sailing": "Rotte costiere in barca, tappe a terra.",
        }
        lines.append("")
        if travel_mode_lower in mode_labels:
            lines.append(f"{mode_labels[travel_mode_lower]}: {mode_descriptions[travel_mode_lower]}")
        if rentals:
            lines.append("")
            lines.append("Dove noleggiare il van:")
            for item in rentals:
                entry = item["name"]
                if item.get("price"):
                    entry += f" — {item['price']}"
                lines.append(entry)
                if item.get("description"):
                    lines.append(f"   {item['description']}")
                lines.append(f"   {item['link']}")

        itinerary_days = email_content.get("itinerary_days", [])
        if itinerary_days:
            lines.append("L'itinerario:")
            names_by_link = {r.get("link"): r.get("name") for r in email_content.get("resources", [])}
            for day in itinerary_days:
                lines.append(day.get("day_label", ""))
                for link in day.get("links") or []:
                    if link in names_by_link:
                        lines.append(f"- {names_by_link[link]}")
                if day.get("transition"):
                    lines.append(f"  {day['transition']}")
            lines.append("")

        appendix = email_content.get("appendix", {})
        if appendix:
            shown = {r.get("link") for r in resources if r.get("link")}
            if hero_link:
                shown.add(hero_link)
            urls: list[str] = []
            for _label, items in appendix.get("groups", []):
                for i in items or []:
                    link = i.get("link")
                    if link and link not in shown and link not in urls:
                        urls.append(link)
            for u in appendix.get("source_links", []):
                if isinstance(u, dict) and u.get("link"):
                    link = u["link"]
                    if link not in shown and link not in urls:
                        urls.append(link)
            urls = urls[:3]
            if urls:
                lines.append("")
                lines.append("Fonti:")
                lines.extend(urls)
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

    async def _explore(
        self,
        destination: str | None,
        tool_calls: list[dict],
        resolved: ResolvedDestinations | None = None,
    ) -> list[dict]:
        """One explore query per resolved destination (never the joined string:
        joining two cities with "e" breaks the search). When the resolved list
        is empty, fall back to the effective destination string. If total
        anchors are still empty, one plain fallback query per destination."""
        names = [p.name for p in (resolved.destinations if resolved else []) if p.name]
        if not names and destination:
            names = [destination]
        if not names:
            return []
        anchors: list[dict] = []
        for name in names:
            query = f"quartieri e luoghi chiave in {name}"
            try:
                res = await maps.research(query, timeout=self._serpapi_timeout, api_key=self._serpapi_api_key)
            except Exception as exc:  # noqa: BLE001 — exploration must never abort the trip
                logger.warning("google_maps explore: error %s: %s", type(exc).__name__, exc)
                tool_calls.append({"engine": "google_maps", "params": {"q": query},
                                   "error": type(exc).__name__})
                continue
            self._log_call(tool_calls, "google_maps", {"q": query}, res)
            anchors.extend(res)
        if not anchors:
            for name in names:
                fallback = f"cose da vedere a {name}"
                try:
                    res = await maps.research(fallback, timeout=self._serpapi_timeout,
                                              api_key=self._serpapi_api_key)
                except Exception as exc:  # noqa: BLE001 — exploration must never abort the trip
                    logger.warning("google_maps explore fallback: error %s: %s", type(exc).__name__, exc)
                    tool_calls.append({"engine": "google_maps", "params": {"q": fallback},
                                       "error": type(exc).__name__})
                    continue
                self._log_call(tool_calls, "google_maps", {"q": fallback}, res)
                anchors.extend(res)
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

    def _build_places_query(self, destination: str | None, intent: TripIntent, trip: TripResponse) -> str:
        """Build a targeted accommodation query based on travel_mode and accommodation_style."""
        if not destination:
            return "hotels"
        tm = (intent.travel_mode or "").lower()
        acc = (intent.accommodation_style or "").lower()
        stay_pref = trip.stay_preference

        # Explicit stay_preference from form takes priority
        if stay_pref and stay_pref not in (None, "indifferente"):
            return f"{stay_pref} stays in {destination}"

        # Derive from travel_mode/accommodation_style
        if tm == "van_life" or acc == "van":
            return f"campeggio {destination}"
        if tm == "sailing" or acc == "boat":
            return f"porto marina ormeggio barca a vela in {destination}"
        if tm == "road_trip" or acc == "camping":
            return f"campeggio area sosta camper in {destination}"
        if acc == "homestay":
            return f"homestay guesthouse B&B in {destination}"
        if acc == "hotel":
            return f"hotel in {destination}"

        # Default fallback
        return f"hotels in {destination}"

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
                tool_calls.append({"engine": engine, "params": params, "error": type(exc).__name__})
                return []
            self._log_call(tool_calls, engine, params, res)
            return res

        # Targeted queries go to maps verbatim: the model already writes mode-aware queries.
        maps_results = await asyncio.gather(*(
            guarded(maps.research(q, timeout=self._serpapi_timeout, api_key=self._serpapi_api_key),
                    "google_maps", {"q": q})
            for q in targeted_queries
        ))

        # Flight matrix: the LLM decides per trip (intent.needs_flights); code only executes.
        # Legacy form travel_mode is NOT consulted: a van rented on arrival still needs a flight.
        departures = departure_codes or _valid_iata([intent.departure_airport_code])
        arrivals = (
            _valid_iata([p.airport_code for p in resolved.destinations])
            or _valid_iata([intent.destination_airport_code])
        )
        if not departures or not arrivals:
            skipped_reason = "no_airports"
        elif not intent.needs_flights:
            skipped_reason = "no_flights_needed"
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
        chosen = await self._revalidate_winner(best, candidates, tool_calls) if best else None
        flights_list = [chosen[1]] if chosen else []
        winning_window = chosen[0][0] if chosen else (flight_windows[0] if flight_windows else (trip.start_date, trip.end_date))

        check_in = trip.start_date or winning_window[0]
        check_out = trip.end_date or winning_window[1]

        # Build targeted places query based on travel_mode and accommodation_style
        places_query = self._build_places_query(destination, intent, trip)
        stays = await guarded(
            places.search(destination=destination, query=places_query, check_in_date=check_in, check_out_date=check_out,
                          timeout=self._serpapi_timeout, api_key=self._serpapi_api_key),
            "google_hotels", {"q": places_query, "check_in_date": check_in, "check_out_date": check_out},
        )
        if not stays and destination and places_query == f"campeggio {destination}":
            logger.info("google_hotels: empty/error for van query, retrying alternate campsite in %s", destination)
            alt_query = f"campsite {destination}"
            stays = await guarded(
                places.search(destination=destination, query=alt_query,
                              check_in_date=check_in, check_out_date=check_out,
                              timeout=self._serpapi_timeout, api_key=self._serpapi_api_key),
                "google_hotels", {"q": alt_query, "check_in_date": check_in,
                                  "check_out_date": check_out},
            )
        if not stays:
            logger.info("google_hotels: empty for mode query, retrying generic hotels in %s", destination)
            retry_query = f"hotels in {destination}" if destination else "hotels"
            stays = await guarded(
                places.search(destination=destination, query=retry_query,
                              check_in_date=check_in, check_out_date=check_out,
                              timeout=self._serpapi_timeout, api_key=self._serpapi_api_key),
                "google_hotels", {"q": retry_query, "check_in_date": check_in,
                                  "check_out_date": check_out},
            )

        # Van rental research: one extra places query, van trips only.
        travel_mode = (intent.travel_mode or "").lower()
        accommodation_style = (intent.accommodation_style or "").lower()
        if destination and (travel_mode == "van_life" or accommodation_style == "van"):
            rental_query = f"noleggio camper van {destination}"
            rentals = await guarded(
                places.search(destination=destination, query=rental_query,
                              check_in_date=check_in, check_out_date=check_out,
                              timeout=self._serpapi_timeout, api_key=self._serpapi_api_key),
                "google_hotels", {"q": rental_query, "check_in_date": check_in,
                                  "check_out_date": check_out, "rental": True},
            )
            for rental in rentals:
                rental["rental"] = True
            stays = [*stays, *rentals]

        maps_items = [*anchors, *(i for lst in maps_results for i in lst)]
        linked_maps = [i for i in maps_items if i.get("link") and not _is_junk_link(i.get("link"))]
        rescued_junk = 0
        for it in maps_items:
            if not it.get("link") or not _is_junk_link(it.get("link")):
                continue
            generated = _maps_search_link(it.get("name"), it.get("address"))
            if generated is None:
                continue
            it["link"] = generated
            linked_maps.append(it)
            rescued_junk += 1
        if rescued_junk:
            logger.info("maps corpus: rescued %d junk-domain entries with generated Maps links", rescued_junk)
        rescued = 0
        nameless_drops: list = []
        for it in maps_items:
            if it.get("link"):
                continue
            generated = _maps_search_link(it.get("name"), it.get("address"))
            if generated is None:
                nameless_drops.append(it.get("name"))
                continue
            it["link"] = generated
            linked_maps.append(it)
            rescued += 1
        if rescued:
            logger.info("maps corpus: rescued %d link-less entries with generated Maps links", rescued)
        if nameless_drops:
            logger.warning("maps corpus: dropped %d link-less entries: %s", len(nameless_drops), nameless_drops)

        corpus = {
            "flights": [{k: v for k, v in f.items() if k != "_meta"} for f in flights_list],
            "maps": dedupe_cap(linked_maps, cap=CORPUS_CAP),
            "places": stays,
        }
        geo_block = {
            "resolved": [p.model_dump() for p in resolved.destinations],
            "departure_codes": departure_codes or _valid_iata([intent.departure_airport_code]),
            "skipped_flights_reason": skipped_reason,
            "flight_rationale": intent.flight_rationale,
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
    def _apply_jev_scores(research: dict, decisions: dict) -> None:
        """Re-rank corpus flights/POIs with T3 scoring before _curate. The scores
        map is empty (no per-item Jev scores yet): defaults keep order stable while
        budget_sensitive already drives price weighting. Never invents links."""
        budget_sensitive = decisions.get("budget_sensitive")
        if not isinstance(budget_sensitive, bool):
            budget_sensitive = False
        scores: dict[str, float] = {}
        corpus = research.get("corpus", {})
        flights_list = corpus.get("flights", []) or []
        if flights_list:
            best = pick_best_flight(flights_list, scores, budget_sensitive)
            if best is not None:
                corpus["flights"] = [best]
        maps_items = corpus.get("maps", []) or []
        if maps_items:
            corpus["maps"] = pick_top_pois(maps_items, scores, limit=len(maps_items))

    #: Re-probe the winning flight combo once before compose: if the price moved
    #: up more than this fraction (or the link is gone), fall back to the next
    #: cheapest candidate. Fail-open: errors keep the original winner.
    PRICE_RISE_SWITCH = 0.15

    async def _revalidate_winner(
        self,
        winner: tuple[tuple[str, str | None], str, str, dict],
        candidates: list[tuple[tuple[str, str | None], str, str, dict]],
        tool_calls: list[dict],
    ) -> tuple[tuple[str, str | None], str, str, dict] | None:
        (window, arrival, departure), flight = winner[0], winner[1]
        old_price = flight.get("price_eur")
        try:
            fresh = await flights.search(departure, arrival, window[0], window[1],
                                         timeout=self._serpapi_timeout, api_key=self._serpapi_api_key)
        except Exception as exc:  # noqa: BLE001 — validation must never abort the trip
            logger.warning("flight revalidation failed, keeping winner: %s", type(exc).__name__)
            tool_calls.append({"engine": "google_flights", "revalidated": False, "reason": "error"})
            return winner
        match = next((f for f in fresh if f.get("link") and f.get("link") == flight.get("link")), None)
        if match is None:
            backups = self._ranked_backups(winner, candidates)
            tool_calls.append({"engine": "google_flights", "revalidated": False, "reason": "link_gone"})
            return backups[0] if backups else winner
        new_price = match.get("price_eur")
        if (isinstance(old_price, (int, float)) and isinstance(new_price, (int, float))
                and old_price > 0 and (new_price - old_price) / old_price > self.PRICE_RISE_SWITCH):
            backups = self._ranked_backups(winner, candidates)
            logger.info("flight revalidation: price %.0f -> %.0f, switching to backup", old_price, new_price)
            tool_calls.append({"engine": "google_flights", "revalidated": True, "reason": "price_moved"})
            return backups[0] if backups else winner
        tool_calls.append({"engine": "google_flights", "revalidated": True, "reason": "confirmed"})
        return winner

    @staticmethod
    def _ranked_backups(
        winner: tuple[tuple[str, str | None], str, str, dict],
        candidates: list[tuple[tuple[str, str | None], str, str, dict]],
    ) -> list[tuple[tuple[str, str | None], str, str, dict]]:
        """Candidates by ascending price, winner excluded, links deduped."""
        ranked = sorted(
            candidates,
            key=lambda cf: cf[1].get("price_eur") if isinstance(cf[1].get("price_eur"), (int, float)) else float("inf"),
        )
        out, seen = [], set()
        for combo, f in ranked:
            link = f.get("link")
            if not link or link == winner[1].get("link") or link in seen:
                continue
            seen.add(link)
            out.append((combo, f))
        return out

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
            "rationale": cur.rationale,
        }
        if not any([curated["flights"], curated["maps"], curated["places"]]):
            # merit fallback: keep corpus top items rather than aborting a researched trip
            curated = {
                "flights": corpus["flights"][:3],
                "maps": corpus["maps"][:3],
                "places": corpus["places"][:3],
                "rationale": cur.rationale,
            }
        return curated

    async def _plan_itinerary(self, trip: TripResponse, intent: TripIntent, curated: dict) -> TripPlan:
        from src.core.models import TripPlan
        from src.core.prompts import build_plan_prompt
        from src.core.trip_plan import sanitize_plan
        from datetime import date
        if not trip.start_date or not trip.end_date:
            return TripPlan()
        try:
            days = (date.fromisoformat(trip.end_date) - date.fromisoformat(trip.start_date)).days + 1
        except ValueError:
            return TripPlan()
        if days <= 0:
            return TripPlan()
        try:
            raw = await self._llm.extract(
                build_plan_prompt(trip, intent,
                                  self._render_flights(curated["flights"], numbered=True),
                                  self._render_maps(curated["maps"], numbered=True),
                                  self._render_places(curated["places"], numbered=True),
                                  days),
                TripPlan,
            )
            return sanitize_plan(raw, len(curated["flights"]), len(curated["maps"]), len(curated["places"]))
        except Exception as exc:
            logger.warning("trip plan skipped: %s: %s", type(exc).__name__, exc)
            return TripPlan()

    async def _compose_email(
        self, trip: TripResponse, intent: TripIntent, research: dict
    ) -> tuple[dict, str, str, dict]:
        corpus, curated = research["corpus"], research["curated"]
        trip_plan = research.get("trip_plan", TripPlan())
        if trip_plan.days:
            research["tool_calls"].append({"engine": "jev-itinerary", "days": len(trip_plan.days)})
        else:
            research["tool_calls"].append({"engine": "jev-itinerary", "skipped": True})
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
        content = self._ensure_flight_hero(content, curated)
        content = self._apply_curated_flight_prices(content, curated)
        content = self._clean_resource_prices(content)

        content["honest_note"] = HONEST_NOTE
        content["cta"] = CTA
        content = strip_bracket_ids(content)
        from src.core.feedback_token import make_token
        from src.settings import get_settings

        settings = get_settings()
        base = getattr(settings, "feedback_base_url", "https://xen-ia.github.io/nostos")
        token = make_token(self._trip_id, settings.api_token or "dev-secret", ttl_days=settings.feedback_token_ttl_days)
        content["feedback_link"] = f"{base}/feedback.html?trip_id={self._trip_id}&token={token}"
        content["sections_map"] = {
            "flights": [r["link"] for r in curated["flights"] if r.get("link")],
            "places": [r["link"] for r in curated["places"] if r.get("link")],
            "maps": [r["link"] for r in curated["maps"] if r.get("link")],
        }
        content["appendix"] = self._build_appendix(
            research,
            exclude_links={r["link"] for r in content["resources"] if r.get("link")},
            allowed_links=set(allowed.links),
        )
        # Pass intent fields for email template sections
        content["travel_mode"] = intent.travel_mode
        content["mobility"] = intent.mobility_preferences
        content["accommodation_style"] = intent.accommodation_style
        flight_links = [r["link"] for r in curated["flights"] if r.get("link")]
        maps_links = [r["link"] for r in curated["maps"] if r.get("link")]
        places_links = [r["link"] for r in curated["places"] if r.get("link")]
        itinerary_days = []
        for day in trip_plan.days:
            links = ([flight_links[i] for i in day.flight_refs if i < len(flight_links)]
                     + [maps_links[i] for i in day.poi_refs if i < len(maps_links)]
                     + [places_links[i] for i in day.stay_refs if i < len(places_links)])
            itinerary_days.append({"day_label": day.day_label, "links": links, "transition": day.transition})
        content["itinerary_days"] = itinerary_days
        body_text = self._compose_body_text(content)
        body_html = build_html_email(content)
        package = {
            "intent": intent.model_dump(),
            "geo": research.get("geo", {}),
            "corpus": corpus,
            "curated": curated,
            "curated_rationale": curated.get("rationale", ""),
            "trip_plan": research.get("trip_plan", TripPlan()).model_dump(),
            "tool_calls": research["tool_calls"],
        }
        return content, body_text, body_html, package

    @staticmethod
    def _build_appendix(research: dict, exclude_links: set[str] | None = None,
                        allowed_links: set[str] | None = None) -> dict:
        """Sources backing SHOWN content only: curated (allowed) corpus links minus
        every rendered link, capped at 3, junk-filtered. Uncurated corpus items
        (e.g. random houses never picked) never surface here. `allowed_links=None`
        keeps the legacy corpus-minus-rendered behavior (tests only)."""
        corpus = research["corpus"]
        excluded = set(exclude_links or ())
        excluded.add("https://xen-ia.github.io/nostos")

        def brief_items(items: list[dict]) -> list[dict]:
            out = []
            for it in items:
                link = it.get("link")
                if not link or _is_junk_link(link) or link in excluded:
                    continue
                if allowed_links is not None and link not in allowed_links:
                    continue
                if link in (i["link"] for i in out):
                    continue
                out.append({"name": it.get("name") or it.get("airline"), "link": link})
            return out

        # Cap the total links across groups at 3, keeping group order
        # Voli → Dove stare → Cosa fare; drop empty groups.
        raw_groups = [
            ("Voli", brief_items(corpus["flights"])),
            ("Dove stare", brief_items(corpus["places"])),
            ("Cosa fare", brief_items(corpus["maps"])),
        ]
        groups: list[tuple[str, list[dict]]] = []
        remaining = 3
        for label, items in raw_groups:
            take = items[:remaining]
            remaining -= len(take)
            if take:
                groups.append((label, take))

        # Only include the winning flight link when not already shown
        # (not all probed combinations) and backed by the curation.
        source_links = []
        if corpus.get("flights") and remaining > 0:
            flight = corpus["flights"][0]
            if (flight.get("link") and not _is_junk_link(flight.get("link"))
                    and flight["link"] not in excluded
                    and (allowed_links is None or flight["link"] in allowed_links)):
                source_links.append({"name": flight.get("airline", "Volo selezionato"), "link": flight["link"]})

        return {
            "groups": groups,
            "source_links": source_links,
        }

    @staticmethod
    def _render_flights(items: list[dict], numbered: bool = False) -> str:
        if not items:
            return "no flights available"

        def label(i: int) -> str:
            return f"[F{i}] " if numbered else ""

        def flight_line(i: int, it: dict) -> str:
            price = it.get("price_eur")
            price_txt = f", {price} EUR" if isinstance(price, (int, float)) else ""
            return (f"{label(i)}{it.get('airline')}, {it.get('from')} -> {it.get('to')}, "
                    f"departure {it.get('departure_date')}{price_txt} — {it.get('link')}")

        return "\n".join(flight_line(i, it) for i, it in enumerate(items))

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

        def place_line(i: int, it: dict) -> str:
            price = it.get("price_per_night_eur")
            price_txt = f"{price} EUR/night" if isinstance(price, (int, float)) else "prezzo non indicato"
            return f"{label(i)}{it.get('name')} — {price_txt} — {it.get('link')}"

        return "\n".join(place_line(i, it) for i, it in enumerate(items))

    @staticmethod
    def _clean_resource_prices(content: dict) -> dict:
        """Blank prices that are missing or leaked 'None ...' strings (SerpAPI
        nulls echoed by the LLM), so neither HTML pills nor text lines print them."""
        for resource in content.get("resources", []):
            price = resource.get("price")
            if not price or str(price).strip().lower().startswith("none"):
                resource["price"] = ""
        return content

    @staticmethod
    def _ensure_flight_hero(content: dict, curated: dict) -> dict:
        """Deterministic hero guarantee: if the LLM cited no curated flight,
        append one built from the winning researched flight (never invented:
        name/date/price/link all come from SerpAPI data)."""
        flight_links = {r.get("link") for r in content.get("resources", [])}
        for f in curated.get("flights", []):
            if not f.get("link") or f["link"] in flight_links:
                continue
            name = f"Volo {(f.get('airline') or '').strip()} · {(f.get('from') or '').strip()} – {(f.get('to') or '').strip()}".strip()
            desc = f"Partenza {f['departure_date']}" if f.get("departure_date") else ""
            price = f"{f['price_eur']} EUR" if isinstance(f.get("price_eur"), (int, float)) else ""
            content.setdefault("resources", []).append(
                {"name": name or "Volo", "description": desc, "price": price, "link": f["link"]})
            logger.info("flight hero force-included from curated winner: %s", f["link"])
            break
        return content

    @staticmethod
    def _apply_curated_flight_prices(content: dict, curated: dict) -> dict:
        """Overwrite flight price prose with researched numbers: the LLM writes
        price text freely and validation only checks links, so figures can drift."""
        by_link = {f.get("link"): f for f in curated.get("flights", []) if f.get("link")}
        for resource in content.get("resources", []):
            flight = by_link.get(resource.get("link"))
            if flight is None:
                continue
            price = flight.get("price_eur")
            resource["price"] = f"{price} EUR" if isinstance(price, (int, float)) else ""
        return content
