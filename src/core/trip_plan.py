"""TripPlan validation: per-category ref filtering + URL-free transitions."""
import logging
import re

from src.core.models import TripPlan

logger = logging.getLogger("nostos.trip_plan")

MAX_DAYS = 7
_URL_RE = re.compile(r"https?://|www\.")
_FLIGHT_WORD_RE = re.compile(r"\bvoli?\b", re.IGNORECASE)


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
    return plan.model_copy(update={"days": kept})
