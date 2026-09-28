from src.core.orchestrator import TripOrchestrator
from src.services.apis.email import _render_arrival, _render_scenes, build_html_email

CONTENT = {
    "opening": "Apertura.",
    "understanding": "Comprensione.",
    "cta": "CTA.",
    "honest_note": "Nota.",
    "resources": [
        {"name": "Volino", "description": "", "price": "300 EUR", "link": "https://f.example"},
        {"name": "Posto", "description": "", "price": "", "link": "https://m.example"},
    ],
    "sections_map": {
        "flights": ["https://f.example"],
        "places": [],
        "maps": ["https://m.example"],
    },
    "appendix": {
        "groups": [
            ("Voli", [{"name": "Altro volo", "link": "https://f.example/2"}]),
            ("Dove stare", []),
            ("Cosa fare", [{"name": "POI due", "link": "https://m.example/2"}]),
        ],
        "source_links": [{"name": "Volo selezionato", "link": "https://gf.example"}],
    },
}


def test_empty_group_not_rendered_but_nonempty_is():
    html = build_html_email(CONTENT)
    assert ">Voli<" not in html and ">Dove stare<" not in html and ">Cosa fare<" not in html


def test_scenes_render_in_order_with_single_links():
    content = dict(CONTENT)
    content["arrival"] = "Atterri la sera."
    content["scenes"] = [
        {"title": "Festo", "prose": "Pietre calde e dakos.", "place_links": ["https://m.example"]},
        {"title": "Sud", "prose": "Sale e vento.", "place_links": []},
    ]
    html = build_html_email(content)
    assert html.index("Atterri la sera.") < html.index("Festo") < html.index("Sud")
    assert html.count('href="https://m.example"') == 1  # one Vedi link per scene link


def test_appendix_sources_present_with_all_links():
    html = build_html_email(CONTENT)
    assert "<details" not in html and "</details>" not in html
    assert "https://f.example/2" in html and "https://m.example/2" in html
    assert "https://gf.example" in html
    assert "Volo selezionato" in html


def test_no_quota_heading():
    html = build_html_email(CONTENT)
    assert "tre punti" not in html.lower()


def test_leftover_resources_render_flat():
    content = dict(CONTENT)
    content["resources"] = [
        {"name": "Orfano", "description": "", "price": "", "link": "https://orphan.example"},
    ]
    content["sections_map"] = {}
    html = build_html_email(content)
    assert "Orfano" not in html  # orphan resources never render without a scene link


def test_render_arrival_empty_is_empty():
    assert _render_arrival("") == ""
    assert _render_arrival("   ") == ""


def test_render_scenes_reuses_cards_and_skips_orphans():
    cards = {"https://x.it": {"name": "Taverna X", "link": "https://x.it"}}
    html = _render_scenes(
        [{"title": "Sera", "prose": "Luci calde e sale.",
          "place_links": ["https://x.it", "https://orphan.example"]}],
        cards)
    assert "Sera" in html and "Luci calde" in html
    assert 'href="https://x.it"' in html
    assert "orphan.example" not in html  # orphan links never render


def test_scene_link_has_single_href():
    content = dict(CONTENT)
    content["scenes"] = [
        {"title": "Festo", "prose": "Pietre calde e dakos.", "place_links": ["https://m.example"]},
    ]
    html = build_html_email(content)
    assert html.count('href="https://m.example"') == 1, "scene title is plain text, Vedi the only link"


def test_stars_normalized_to_stelle():
    from src.services.apis.email import _render_card
    html = _render_card({"name": "Festo", "description": "Punto storico, 4.3 stars",
                         "price": "", "link": "https://x.it"})
    assert "4.3 stelle" in html and "stars" not in html


def test_trip_summary_renders_when_present():
    content = dict(CONTENT)
    content["trip_summary"] = "Creta · 30 lug – 30 ago 2027 · coppia (2)"
    html = build_html_email(content)
    assert "Creta · 30 lug" in html


def test_trip_summary_absent_renders_nothing():
    html = build_html_email(CONTENT)
    assert "trip-summary" not in html


def test_selection_heading_ignored_in_acts_world():
    content = dict(CONTENT)
    content["selection_heading"] = "Ecco la selezione per Creta"
    html = build_html_email(content)
    assert "Ecco la selezione per Creta" not in html
    assert "Ecco i punti di partenza" not in html


def test_logistics_flight_single_link_with_button():
    html = build_html_email(CONTENT)
    assert html.count("https://f.example\"") == 1, "logistics keeps only the Vedi il volo link"
    assert "Vedi il volo" in html


def test_card_and_feedback_box_keep_dark_classes():
    html = build_html_email(CONTENT)
    assert "d-card" in html and "d-cta" in html


def test_draft_note_renders_after_understanding():
    content = dict(CONTENT)
    content["draft_note"] = "Prima bozza di Xen-IA: il viaggio vero insieme."
    html = build_html_email(content)
    assert "Prima bozza di Xen-IA" in html


def test_draft_note_absent_renders_nothing():
    html = build_html_email(CONTENT)
    assert "draft-note" not in html


def test_followup_button_label():
    content = dict(CONTENT)
    content["feedback_link"] = "https://x.example/fb"
    html = build_html_email(content)
    assert "Parliamone insieme" in html
    assert "Lascia un feedback" not in html


def test_body_text_is_twin_of_acts_html():
    """Twin rule: every HTML string (arrival, scene titles+prose+links,
    logistics, draft note) appears in the text body in the same order."""
    content = dict(CONTENT)
    content["draft_note"] = "Prima bozza."
    content["arrival"] = "Atterri la sera."
    content["scenes"] = [
        {"title": "Festo", "prose": "Pietre calde e dakos.", "place_links": ["https://m.example"]},
        {"title": "Sud", "prose": "Sale e vento.", "place_links": []},
    ]
    content["logistics"] = "Volo A · 100 EUR"
    text = TripOrchestrator._compose_body_text(content)
    html = build_html_email(content)
    order = ["Apertura.", "Comprensione.", "Prima bozza.", "Atterri la sera.",
             "Festo", "Pietre calde e dakos.", "https://m.example",
             "Sud", "Sale e vento.", "Volo A · 100 EUR", "CTA.", "Nota."]
    positions = [text.index(s) for s in order]
    assert positions == sorted(positions), "twin strings must follow HTML order"
    for s in ("Atterri la sera.", "Festo", "Pietre calde e dakos.",
              "https://m.example", "Sud", "Volo A · 100 EUR"):
        assert s in html


def test_acts_render_in_order():
    content = dict(CONTENT)
    content["arrival"] = "Atterri la sera."
    content["scenes"] = [
        {"title": "Festo", "prose": "Pietre calde e dakos.", "place_links": ["https://m.example"]},
        {"title": "Sud", "prose": "Sale e vento.", "place_links": []},
    ]
    content["logistics"] = "Volo A · 100 EUR"
    html = build_html_email(content)
    assert html.index("Atterri la sera") < html.index("Festo") < html.index("Sud")
    assert "Volo A" in html
    assert '<table class="card-frame"' not in html
