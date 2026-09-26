"""TripPlan validation: per-category ref filtering + URL-free transitions."""
import logging
import re

from src.core.models import DayStop, TripPlan

logger = logging.getLogger("nostos.trip_plan")

MAX_DAYS = 7
_URL_RE = re.compile(r"https?://|www\.")
_FLIGHT_WORD_RE = re.compile(r"\bvoli?\b", re.IGNORECASE)


def transition_names_a_stop(transition: str, stop_names: list[str]) -> bool:
    """True when the transition names at least one stop (significant word,
    len>4, case-insensitive). Generic filler ('tappe corte') fails."""
    text = (transition or "").lower()
    words = set()
    for name in stop_names:
        for token in re.findall(r"[a-zà-ÿ]+", (name or "").lower()):
            if len(token) > 4:
                words.add(token)
    return any(w in text for w in words)


def _strip_flight_mentions(transition: str) -> str:
    """Drop sentences naming flights (ungrounded when no flight was curated)."""
    kept = [s.strip() for s in transition.split(". ") if s.strip() and not _FLIGHT_WORD_RE.search(s)]
    out = ". ".join(kept).strip()
    if out and not out.endswith("."):
        out += "."
    return out


def sanitize_plan(plan: TripPlan, flight_n: int, maps_n: int, places_n: int) -> TripPlan:
    kept = []
    seen_pois: set[int] = set()
    seen_stays: set[int] = set()
    for day in plan.days[:MAX_DAYS]:
        flights = [i for i in day.flight_refs if 0 <= i < flight_n]
        pois = [i for i in day.poi_refs if 0 <= i < maps_n and i not in seen_pois]
        stays = [i for i in day.stay_refs if 0 <= i < places_n and i not in seen_stays]
        dropped = (len(day.flight_refs) - len(flights) + len(day.poi_refs) - len(pois)
                   + len(day.stay_refs) - len(stays))
        if dropped:
            logger.warning("trip plan ref %d out of range/duplicate dropped (%s)", dropped, day.day_label)
        seen_pois.update(pois)
        seen_stays.update(stays)
        transition = day.transition
        if transition and _URL_RE.search(transition):
            logger.warning("trip plan URL stripped from transition (%s)", day.day_label)
            transition = ""
        if transition and flight_n == 0 and _FLIGHT_WORD_RE.search(transition):
            logger.warning("trip plan flight mention stripped, no curated flights (%s)", day.day_label)
            transition = _strip_flight_mentions(transition)
        if not flights and not pois and not stays and not transition:
            continue
        kept.append(day.model_copy(update={"flight_refs": flights, "poi_refs": pois,
                                            "stay_refs": stays, "transition": transition}))
    if len(kept) < MAX_DAYS:
        missing_flights = [i for i in range(flight_n) if i not in seen_flights(kept)]
        missing_pois = [i for i in range(maps_n) if i not in seen_pois]
        missing_stays = [i for i in range(places_n) if i not in seen_stays]
        if missing_flights or missing_pois or missing_stays:
            logger.info("trip plan coverage: %d refs appended to final phase",
                        len(missing_flights) + len(missing_pois) + len(missing_stays))
            kept.append(DayStop(day_label="Altre tappe lungo il percorso",
                                flight_refs=missing_flights, poi_refs=missing_pois,
                                stay_refs=missing_stays))
    return plan.model_copy(update={"days": kept})


def seen_flights(days: list) -> set[int]:
    return {i for day in days for i in day.flight_refs}
