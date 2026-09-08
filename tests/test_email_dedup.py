from src.services.apis.email import build_html_email

def test_no_duplicate_mobility_when_van_life():
    content = {"opening":"x","understanding":"y","resources":[],"cta":"c","honest_note":"n","travel_mode":"van_life","mobility":["auto","van"],"sections_map":{},"appendix":{"groups":[],"source_links":[]}}
    html = build_html_email(content)
    assert html.count("Mezzi") == 1  # solo dentro Vita in van, non anche Come spostarti
    assert "Come spostarti" not in html

def test_mobility_only_when_fixed():
    content = {"opening":"x","understanding":"y","resources":[],"cta":"c","honest_note":"n","travel_mode":"fixed","mobility":["auto"],"sections_map":{},"appendix":{"groups":[],"source_links":[]}}
    html = build_html_email(content)
    assert "Come spostarti" in html
