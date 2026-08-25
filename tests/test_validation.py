# tests/test_validation.py
from datetime import date

from src.core.validation import (
    AllowedResources,
    build_allowed_resources,
    sanitize_windows,
    validate_resources,
)

FLIGHTS = [{"name": "ANA", "price_eur": 320, "link": "https://f.example/ana"}]
MAPS = [{"name": "Senso-ji", "rating": 4.7, "link": "https://m.example/sensoji"}]
PLACES = [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://p.example/ryokan"}]


def test_build_allowed_collects_links_and_names():
    allowed = build_allowed_resources(FLIGHTS, MAPS, PLACES)
    assert isinstance(allowed, AllowedResources)
    assert "https://f.example/ana" in allowed.links
    assert "senso-ji" in allowed.names


def test_valid_resource_passes():
    allowed = build_allowed_resources(FLIGHTS, MAPS, PLACES)
    report = validate_resources(
        [{"name": "Senso-ji", "description": "", "price": "", "link": "https://m.example/sensoji"}],
        allowed,
    )
    assert len(report.valid) == 1 and report.invalid == []


def test_hallucinated_resource_is_invalid():
    allowed = build_allowed_resources(FLIGHTS, MAPS, PLACES)
    report = validate_resources(
        [{"name": "Museum of Modern Art", "description": "", "price": "", "link": "https://www.moma.org/"}],
        allowed,
    )
    assert report.valid == [] and len(report.invalid) == 1


def test_name_match_saves_missing_link():
    allowed = build_allowed_resources(FLIGHTS, MAPS, PLACES)
    report = validate_resources(
        [{"name": "Ryokan X", "description": "", "price": "95 EUR/notte", "link": ""}],
        allowed,
    )
    assert len(report.valid) == 1


def test_sanitize_windows_rejects_past_and_inverted_keeps_max2():
    today = date(2026, 8, 23)
    windows = [
        {"start": "2026-01-01", "end": "2026-02-01"},   # past -> dropped
        {"start": "2026-10-10", "end": "2026-09-01"},   # inverted -> dropped
        {"start": "2026-09-01", "end": "2026-09-30"},
        {"start": "2026-10-01", "end": "2026-10-31"},
        {"start": "2026-11-01", "end": "2026-11-30"},   # over cap -> dropped
    ]
    assert sanitize_windows(windows, today) == [
        ("2026-09-01", "2026-09-30"),
        ("2026-10-01", "2026-10-31"),
    ]


def test_sanitize_windows_fallback_when_nothing_usable():
    today = date(2026, 8, 23)
    assert sanitize_windows([], today) == [("2026-09-06", "2026-09-13")]
