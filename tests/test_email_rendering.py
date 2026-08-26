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
        "source_links": ["https://gf.example"],
    },
}


def test_empty_group_not_rendered_but_nonempty_is():
    html = build_html_email(CONTENT)
    assert "Voli" in html and "Cosa fare" in html
    assert "Dove stare" not in html.split("<details")[0]  # absent among curated cards


def test_appendix_details_present_with_all_links():
    html = build_html_email(CONTENT)
    assert "<details" in html and "</details>" in html
    assert "https://f.example/2" in html and "https://m.example/2" in html
    assert "https://gf.example" in html


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
    assert "Orfano" in html
