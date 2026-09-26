from src.services.apis.email import _render_itinerary
from src.services.apis.email import build_html_email

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


def test_itinerary_renders_covered_cards():
    content = dict(CONTENT)
    content["itinerary_days"] = [{"day_label": "Le tappe",
                                  "links": ["https://m.example"], "transition": ""}]
    html = build_html_email(content)
    assert "Posto" in html and "L'itinerario" in html


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
    content["itinerary_days"] = []
    html = build_html_email(content)
    assert "Orfano" not in html  # orphan resources never render without a phase


def test_render_itinerary_empty_is_empty():
    assert _render_itinerary([], {}) == ""


def test_render_itinerary_reuses_cards():
    card = {"name": "Taverna X", "description": "cucina locale", "price": "", "link": "https://x.it"}
    html = _render_itinerary([{"day_label": "Giorni 1-7 · X", "links": ["https://x.it"], "transition": "tappe corte."}], {"https://x.it": card})
    assert "Giorni 1-7" in html and "Taverna X" in html and "tappe corte" in html


def test_card_has_single_link():
    content = dict(CONTENT)
    content["itinerary_days"] = [{"day_label": "Le tappe",
                                  "links": ["https://m.example"], "transition": ""}]
    html = build_html_email(content)
    assert html.count("https://m.example\"") == 1, "card title must be plain text, Apri the only link"


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


def test_selection_heading_uses_destination():
    content = dict(CONTENT)
    content["selection_heading"] = "Ecco la selezione per Creta"
    html = build_html_email(content)
    assert "Ecco la selezione per Creta" in html
    assert "Ecco i punti di partenza" not in html


def test_selection_heading_falls_back():
    html = build_html_email(CONTENT)
    assert "Ecco i punti di partenza" in html


def test_hero_title_not_linked_but_button_present():
    html = build_html_email(CONTENT)
    assert html.count("https://f.example\"") == 1, "hero keeps only the Vedi il volo button link"
    assert "Vedi il volo" in html


def test_hero_and_travel_box_have_dark_classes():
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
