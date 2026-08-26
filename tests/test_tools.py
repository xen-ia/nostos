import pytest

from src.services.tools import dedupe_cap
from src.services.tools.maps import research as maps_research
from src.services.tools.places import search as places_search


def test_dedupe_cap_preserves_order_and_caps():
    items = [{"name": "a", "link": "1"}, {"name": "b", "link": "2"}, {"name": "a", "link": "1"}, {"name": "c", "link": "3"}]
    assert dedupe_cap(items, cap=2) == [{"name": "a", "link": "1"}, {"name": "b", "link": "2"}]


async def test_maps_research_issues_single_query(monkeypatch):
    captured = {}

    async def fake_serpapi(params, timeout=60.0, api_key=None):
        captured.update(params)
        return {"local_results": [{"title": "Shibuya", "type": "District", "rating": 4.5}]}

    monkeypatch.setattr("src.services.tools.maps.serpapi_search", fake_serpapi)
    out = await maps_research("quartieri e luoghi chiave a Tokyo")
    assert captured["q"] == "quartieri e luoghi chiave a Tokyo"
    assert out == [{"name": "Shibuya", "type": "District", "rating": 4.5, "reviews_count": None, "address": None, "description": None, "link": None}]


async def test_maps_research_returns_all_results_no_cap(monkeypatch):
    async def fake_serpapi(params, timeout=60.0, api_key=None):
        return {"local_results": [{"title": f"Place {i}"} for i in range(8)]}

    monkeypatch.setattr("src.services.tools.maps.serpapi_search", fake_serpapi)
    out = await maps_research("qualsiasi query")
    assert len(out) == 8
    assert [o["name"] for o in out] == [f"Place {i}" for i in range(8)]


async def test_places_search_drops_linkless_and_caps(monkeypatch):
    async def fake_serpapi(params, timeout=60.0, api_key=None):
        return {"properties": [
            {"name": "NoLink", "type": "hotel", "rate_per_night": {"extracted_lowest": 50}, "total_rate": {}, "essential_info": None, "link": None},
            {"name": "Ok", "type": "hotel", "rate_per_night": {"extracted_lowest": 90}, "total_rate": {}, "essential_info": None, "link": "https://h.example/ok"},
        ]}

    monkeypatch.setattr("src.services.tools.places.serpapi_search", fake_serpapi)
    out = await places_search(destination="Tokyo", check_in_date="2026-09-01", check_out_date="2026-09-10")
    assert [o["name"] for o in out] == ["Ok"]
