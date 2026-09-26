"""Price gate: no 'None ...' strings ever reach prompts or emails."""
from src.core.orchestrator import TripOrchestrator


def test_render_places_omits_missing_price():
    out = TripOrchestrator._render_places(
        [{"name": "Campeggio X", "price_per_night_eur": None, "link": "https://example.com/c"}],
        numbered=True,
    )
    assert "None" not in out
    assert "Campeggio X" in out


def test_render_flights_omits_missing_price():
    out = TripOrchestrator._render_flights(
        [{"airline": "A", "from": "MXP", "to": "AAA", "departure_date": "2026-09-01",
          "price_eur": None, "link": "https://example.com/f"}],
        numbered=True,
    )
    assert "None" not in out
    assert "2026-09-01" in out


def test_clean_resource_prices_strips_none_strings():
    content = {"resources": [
        {"name": "A", "description": "", "price": "None EUR/night", "link": "https://example.com/a"},
        {"name": "B", "description": "", "price": "95 EUR", "link": "https://example.com/b"},
        {"name": "C", "description": "", "price": "", "link": "https://example.com/c"},
    ]}
    TripOrchestrator._clean_resource_prices(content)
    prices = [r["price"] for r in content["resources"]]
    assert prices == ["", "95 EUR", ""]
