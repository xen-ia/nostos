from src.services.apis.email import _e, _render_card, build_html_email
from src.core.orchestrator import TripOrchestrator
from src.core.prompts import build_intent_prompt
from src.core.models import TripIntent
from src.services.tools import _simplify, make_ollama_schema
from src.services.tools.flights import _normalize as _normalize_flight
from src.services.tools.maps import _normalize as _normalize_place
from tests.fakes import make_trip


def test_e_escapes_html():
    assert _e('<script>alert("x")</script>') == "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;"


def test_render_card_escapes_href_and_fields():
    item = {"name": 'A & B', "description": "<b>desc</b>", "price": "100 EUR", "link": 'https://x.com/?a="b"'}
    html = _render_card(item)
    assert "A &amp; B" in html
    assert "&lt;b&gt;desc&lt;/b&gt;" in html
    assert "https://x.com/?a=&quot;b&quot;" in html


def test_render_card_without_optional_fields():
    item = {"name": "X", "link": "https://x.com"}
    html = _render_card(item)
    assert "d-carddesc" not in html
    assert "d-price" not in html


def test_build_html_email_includes_escaped_parts():
    content = {
        "opening": 'Hello "world"',
        "moments": [{"prose": "<i>ok</i>", "place_links": []}],
        "resources": [{"name": "X", "description": "d", "price": "p", "link": "https://x.com"}],
        "cta": "A presto",
        "honest_note": "Auto",
    }
    html = build_html_email(content)
    assert "Hello &quot;world&quot;" in html
    assert "&lt;i&gt;ok&lt;/i&gt;" in html


def test_normalize_flight_maps_fields():
    flight = {
        "flights": [
            {
                "airline": "ANA",
                "departure_airport": {"id": "MXP", "time": "2026-09-01T08:00"},
                "arrival_airport": {"id": "HND"},
            }
        ],
        "price": 320,
        "total_duration": 720,
    }
    out = _normalize_flight(flight, link="https://x.com")
    assert out["airline"] == "ANA"
    assert out["from"] == "MXP"
    assert out["to"] == "HND"
    assert out["departure_date"] == "2026-09-01T08:00"
    assert out["price_eur"] == 320
    assert out["link"] == "https://x.com"


def test_normalize_place_maps_fields():
    place = {
        "title": "Senso-ji",
        "type": "Temple",
        "rating": 4.7,
        "reviews": 1000,
        "address": "Tokyo",
        "description": "Old temple",
        "website": "https://x.com",
    }
    out = _normalize_place(place)
    assert out["name"] == "Senso-ji"
    assert out["type"] == "Temple"
    assert out["rating"] == 4.7
    assert out["link"] == "https://x.com"


def test_ollama_schema_simplifies_nullable():
    from src.core.models import TripIntent

    schema = make_ollama_schema(TripIntent)
    assert isinstance(schema, dict)
    assert "properties" in schema
    assert "$defs" not in schema


def test_simplify_anyof_nullable():
    defs = {}
    node = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    out = _simplify(node, defs)
    assert out["type"] == ["string", "null"]


def test_compose_body_text_letter_mirror():
    content = {
        "opening": "Ciao",
        "draft_note": "Prima bozza.",
        "resources": [
            {"name": "Volo ANA · MXP – HND", "price": "320 EUR", "description": "",
             "link": "https://x.com"},
            {"name": "Ryokan X", "price": "", "description": "", "link": "https://y.com"},
        ],
        "sections_map": {"flights": ["https://x.com"], "maps": ["https://y.com"]},
        "moments": [{"prose": "Luci calde e sale.", "place_links": ["https://y.com"]}],
        "places": [{"name": "Volo ANA · MXP – HND", "price": "320 EUR", "link": "https://x.com"},
                   {"name": "Ryokan X", "price": "", "link": "https://y.com"}],
        "closing": "Facci sapere",
        "cta": "Facci sapere",
        "honest_note": "Auto",
    }
    text = TripOrchestrator._compose_body_text(content)
    assert text.startswith("Ciao")
    order = ["Ciao", "Prima bozza.", "Luci calde e sale.", "https://y.com",
             "I luoghi:", "Volo ANA · MXP – HND — 320 EUR", "https://x.com",
             "Facci sapere", "Auto"]
    positions = [text.index(s) for s in order]
    assert positions == sorted(positions), "twin strings must follow HTML order"
    assert "L'itinerario:" not in text and "Punti di partenza:" not in text


def test_build_intent_prompt_includes_structured_inputs():
    trip = make_trip(
        budget_amount="max 1500 EUR a persona",
        travel_mode="van",
        stay_preference="agriturismo",
    )
    prompt = build_intent_prompt(trip)
    assert "max 1500 EUR a persona" in prompt
    assert "van" in prompt
    assert "agriturismo" in prompt


def test_build_intent_prompt_includes_travelers_fields():
    trip = make_trip(travelers_count=4, travelers_type="famiglia")
    prompt = build_intent_prompt(trip)
    assert "Travelers count: 4" in prompt
    assert "Travelers type: famiglia" in prompt


def test_build_intent_prompt_travelers_type_missing():
    trip = make_trip(travelers_count=1, travelers_type=None)
    prompt = build_intent_prompt(trip)
    assert "Travelers type: not specified" in prompt
