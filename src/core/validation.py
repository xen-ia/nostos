"""Deterministic post-LLM checks: grounding of cited resources and date-window sanity."""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import NamedTuple


class AllowedResources(NamedTuple):
    links: frozenset[str]
    names: frozenset[str]


@dataclass
class ValidationReport:
    valid: list[dict]
    invalid: list[dict]


def build_allowed_resources(flights: list[dict], maps: list[dict], places: list[dict]) -> AllowedResources:
    categories = (flights, maps, places)
    links = frozenset(it["link"] for cat in categories for it in cat if it.get("link"))
    names = frozenset((it.get("name") or "").strip().lower() for cat in categories for it in cat if it.get("name"))
    return AllowedResources(links=links, names=names)


def validate_resources(resources: list[dict], allowed: AllowedResources) -> ValidationReport:
    valid, invalid = [], []
    for res in resources:
        link_ok = bool(res.get("link")) and res["link"] in allowed.links
        name_ok = (res.get("name") or "").strip().lower() in allowed.names
        (valid if (link_ok or name_ok) else invalid).append(res)
    return ValidationReport(valid=valid, invalid=invalid)


def sanitize_windows(windows: list[dict], today: date) -> list[tuple[str, str]]:
    usable: list[tuple[str, str]] = []
    for w in windows:
        try:
            start, end = date.fromisoformat(w["start"]), date.fromisoformat(w["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if start >= today and end >= start:
            usable.append((start.isoformat(), end.isoformat()))
    if not usable:
        fallback_start, fallback_end = today + timedelta(days=14), today + timedelta(days=21)
        return [(fallback_start.isoformat(), fallback_end.isoformat())]
    return usable[:2]
