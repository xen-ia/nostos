from src.services.apis.email import build_html_email

def test_no_mezzi_line_in_van_life_box():
    content = {"opening":"x","understanding":"y","resources":[],"cta":"c","honest_note":"n","travel_mode":"van_life","mobility":["auto","van"],"sections_map":{},"appendix":{"groups":[],"source_links":[]}}
    html = build_html_email(content)
    assert "Mezzi" not in html
    assert "Vita in van" in html  # heading + body prose stay, only the line is gone
    assert "Come spostarti" not in html

def test_no_mezzi_line_when_fixed():
    content = {"opening":"x","understanding":"y","resources":[],"cta":"c","honest_note":"n","travel_mode":"fixed","mobility":["auto"],"sections_map":{},"appendix":{"groups":[],"source_links":[]}}
    html = build_html_email(content)
    assert "Mezzi" not in html  # the line is deleted, not merged
    assert "Come spostarti" not in html
