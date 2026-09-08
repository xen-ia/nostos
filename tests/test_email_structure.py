# tests/test_email_structure.py
import re

from src.core.orchestrator import TripOrchestrator, strip_bracket_ids
from src.core.models import TripIntent
from src.core.prompts import build_curation_prompt, build_email_prompt
from src.services.apis.email import SITE_URL, build_html_email
from tests.fakes import make_trip

BASE = {"opening": "O.", "understanding": "U.", "resources": [], "cta": "C.",
        "honest_note": "N.", "sections_map": {}, "appendix": {"groups": [], "source_links": []}}


def test_no_details_no_block_only_anchors():
    html = build_html_email({**BASE, "travel_mode": "van_life", "mobility": ["auto", "van"],
                             "feedback_link": "https://x.example/f?trip_id=1&token=abc"})
    assert "<details" not in html
    assert "Lascia un feedback" in html
    assert "https://x.example/f?trip_id=1&amp;token=abc" in html


def test_van_box_has_no_mezzi_line():
    html = build_html_email({**BASE, "travel_mode": "van_life", "mobility": ["auto", "van"]})
    assert "Mezzi" not in html
    assert "Vita in van" in html  # heading + body prose stay, only the line is gone


def test_cta_targets_min_44px():
    html = build_html_email({**BASE, "feedback_link": "https://x.example/f"})
    pads = re.findall(r"padding:(\d+)px", html)
    cta_pads = [int(p) for p in pads]
    assert cta_pads and min(cta_pads) >= 14  # 14px vertical padding ≈ 44px target with 16px text


CARD_CONTENT = {**BASE,
                "resources": [{"name": "Hotel X", "description": "Nice place",
                               "price": "100 EUR", "link": "https://h.example/x"}],
                "sections_map": {"maps": ["https://h.example/x"]}}


def test_cards_use_sibling_anchors_no_nesting():
    html = build_html_email({**CARD_CONTENT,
                             "feedback_link": "https://x.example/f"})
    # No anchor may contain another anchor anywhere in the email.
    assert not re.search(r"<a\b[^>]*>(?:(?!</a>).)*<a\b", html, re.S | re.I)
    # Card exposes exactly the title link + the Apri link as siblings.
    cards = re.findall(r'<table class="card-frame".*?</table>', html, re.S)
    assert len(cards) == 1
    assert len(re.findall(r"<a\b", cards[0])) == 2
    assert "Hotel X" in cards[0] and "Apri &rarr;" in cards[0]


def test_reply_gone_in_all_modes():
    with_link = build_html_email({**BASE, "feedback_link": "https://x.example/f"})
    assert "Rispondi per continuare" not in with_link
    assert "mailto:" not in with_link
    assert "Lascia un feedback" in with_link
    without_link = build_html_email({**BASE})
    assert "Rispondi per continuare" not in without_link
    assert "mailto:" not in without_link
    assert "Lascia un feedback" not in without_link


def test_no_empty_button_cells():
    single = build_html_email({**BASE, "feedback_link": "https://x.example/f"})
    assert single.count('class="btn-cell"') == 1
    assert "Lascia un feedback" in single
    none = build_html_email({**BASE})
    assert 'class="btn-cell"' not in none
    assert "Lascia un feedback" not in none
    assert "Rispondi per continuare" not in none
    assert "mailto:" not in none


def test_cta_copy_is_one_way():
    from src.core.orchestrator import CTA
    assert CTA == "Com'è andata? Lasciaci un feedback."
    html = build_html_email({**BASE, "cta": CTA,
                             "feedback_link": "https://x.example/f"})
    assert "IL TUO PARERE" in html.upper()
    assert "IL PROSSIMO PASSO" not in html.upper()
    assert "rispondi" not in html.lower()


def _bracket_content() -> dict:
    return {
        **BASE,
        "opening": "[F0] Collegamento di partenza per il nord.",
        "understanding": "Cerchi mare [M12] e relax [P3] lontano dalle folle.",
        "resources": [{
            "name": "[F0] easyJet, MXP -> INV",
            "description": "Volo [F0] diretto al mattino",
            "price": "[F0] 196 EUR",
            "link": "https://f.example/abc",
        }],
        "sections_map": {"flights": ["https://f.example/abc"]},
    }


def test_bracket_ids_stripped_from_html_and_text():
    cleaned = strip_bracket_ids(_bracket_content())
    html = build_html_email(cleaned)
    text = TripOrchestrator._compose_body_text(cleaned)
    for tag in ("[F0]", "[M12]", "[P3]"):
        assert tag not in html
        assert tag not in text
    assert "Collegamento di partenza per il nord." in html
    assert "Collegamento di partenza per il nord." in text
    assert "196 EUR" in html  # price value survives, only the ID is stripped


def test_hero_flight_excluded_from_resource_groups():
    link = "https://flights.example/abc"
    content = {
        **BASE,
        "resources": [{"name": "Volo easyJet Milano → Inverness", "description": "Diretto",
                       "price": "196 EUR", "link": link}],
        "sections_map": {"flights": [link]},
    }
    html = build_html_email(content)
    assert "Come arrivare" in html and "Vedi il volo" in html  # hero still renders
    assert "Voli" not in html  # hero flight must not reappear as a grouped card
    cards = re.findall(r'<table class="card-frame".*?</table>', html, re.S)
    assert all(link not in card for card in cards)


def test_hero_flight_excluded_but_other_flights_grouped():
    hero = "https://flights.example/hero"
    other = "https://flights.example/other"
    content = {
        **BASE,
        "resources": [
            {"name": "Volo easyJet Milano → Inverness", "description": "", "price": "",
             "link": hero},
            {"name": "Volo Ryanair Bergamo → Edimburgo", "description": "", "price": "",
             "link": other},
        ],
        "sections_map": {"flights": [hero, other]},
    }
    html = build_html_email(content)
    assert "Voli" in html
    assert other in html
    cards = re.findall(r'<table class="card-frame".*?</table>', html, re.S)
    assert all(hero not in card for card in cards)


def test_raw_flight_name_humanized_and_price_deduped():
    hero = "https://flights.example/hero"
    other = "https://flights.example/other"
    content = {
        **BASE,
        "resources": [
            {"name": "easyJet, MXP -> INV, departure 2026-12-21 10:35, 196 EUR",
             "description": "Partenza 2026-12-21, 196 EUR tutto incluso",
             "price": "196 EUR", "link": hero},
            {"name": "Ryanair, BGY -> EDI, departure 2026-12-21 07:00, 250 EUR",
             "description": "Alba a Edimburgo, 250 EUR con bagaglio",
             "price": "250 EUR", "link": other},
        ],
        "sections_map": {"flights": [hero, other]},
    }
    html = build_html_email(content)
    assert "departure 2026-12-21" not in html
    assert "Volo easyJet" in html
    assert "Volo Ryanair" in html
    assert html.count("196 EUR") == 1  # price pill only, description duplicate stripped
    assert html.count("250 EUR") == 1


def test_footer_url_single_occurrence():
    html = build_html_email({**BASE})
    assert html.count(SITE_URL) == 1


def test_email_prompt_requires_human_flight_titles():
    intent = TripIntent(interests=["mare"], style=["lento"], pace="rilassato")
    prompt = build_email_prompt(intent, "easyJet, MXP -> INV", "none", "none",
                                trip=make_trip())
    assert "Volo {airline}" in prompt


def test_curation_prompt_prefers_matching_poi():
    intent = TripIntent(interests=["mare"], style=["lento"], pace="rilassato")
    prompt = build_curation_prompt(make_trip(), intent, "Points of interest:\n[M0] Spiaggia X")
    assert "at least one" in prompt


def test_curation_prompt_quality_bar():
    intent = TripIntent(interests=["mare"], style=["lento"], pace="rilassato")
    prompt = build_curation_prompt(make_trip(), intent, "corpus").lower()
    assert "same hotel chain" in prompt or "hotel chain" in prompt
    assert "stated interest" in prompt
    assert "4.0" in prompt


def _sources_content(resources, appendix_groups, source_links=None):
    links = [r["link"] for r in resources]
    return {
        **BASE,
        "resources": resources,
        "sections_map": {"flights": links[:1], "maps": links[1:]},
        "appendix": {"groups": appendix_groups,
                     "source_links": source_links or []},
    }


def test_sources_exclude_shown_links_and_cap_3():
    hero = "https://flights.example/hero"
    card = "https://hotels.example/card"
    resources = [
        {"name": "Volo", "description": "", "price": "", "link": hero},
        {"name": "Hotel", "description": "", "price": "", "link": card},
    ]
    appendix_groups = [
        ("Voli", [{"name": "dup hero", "link": hero},
                  {"name": "V1", "link": "https://s.example/v1"},
                  {"name": "V2", "link": "https://s.example/v2"}]),
        ("Dove stare", [{"name": "dup card", "link": card},
                        {"name": "S1", "link": "https://s.example/s1"}]),
        ("Cosa fare", [{"name": "P1", "link": "https://s.example/p1"},
                       {"name": "P2", "link": "https://s.example/p2"}]),
    ]
    html = build_html_email(_sources_content(resources, appendix_groups))
    assert hero not in html.split("Fonti</div>", 1)[-1]
    assert card not in html.split("Fonti</div>", 1)[-1]
    sources_block = html.split("Fonti</div>", 1)[-1]
    assert sources_block.count("<li ") <= 3
    assert "https://s.example/v1" in sources_block


def test_sources_empty_renders_nothing():
    link = "https://only.example/x"
    resources = [{"name": "Solo", "description": "", "price": "", "link": link}]
    appendix_groups = [("Voli", [{"name": "dup", "link": link}])]
    html = build_html_email(_sources_content(resources, appendix_groups))
    assert "Fonti</div>" not in html
    assert "<li " not in html


def test_body_text_sources_exclude_shown_and_cap_3():
    hero = "https://flights.example/hero"
    content = {
        "opening": "O.", "understanding": "U.",
        "resources": [{"name": "Volo", "description": "", "price": "",
                       "link": hero}],
        "sections_map": {"flights": [hero]},
        "cta": "C.", "honest_note": "N.",
        "appendix": {"groups": [
            ("Voli", [{"name": "dup", "link": hero},
                      {"name": "V1", "link": "https://s.example/1"},
                      {"name": "V2", "link": "https://s.example/2"},
                      {"name": "V3", "link": "https://s.example/3"},
                      {"name": "V4", "link": "https://s.example/4"}]),
        ], "source_links": []},
    }
    text = TripOrchestrator._compose_body_text(content)
    assert "Fonti:" in text
    after = text.split("Fonti:", 1)[-1]
    assert hero not in after
    urls = [l.strip() for l in after.splitlines() if l.strip().startswith("http")]
    assert len(urls) <= 3


def test_build_appendix_excludes_shown_and_caps_3():
    hero = "https://flights.example/hero"
    card = "https://hotels.example/card"
    research = {"corpus": {
        "flights": [{"airline": "A", "link": hero},
                    {"airline": "B", "link": "https://s.example/v1"}],
        "places": [{"name": "dup card", "link": card},
                   {"name": "S1", "link": "https://s.example/s1"},
                   {"name": "S2", "link": "https://s.example/s2"}],
        "maps": [{"name": "P1", "link": "https://s.example/p1"},
                 {"name": "P2", "link": "https://s.example/p2"}],
    }}
    appendix = TripOrchestrator._build_appendix(research, exclude_links={hero, card})
    total = sum(len(items) for _, items in appendix["groups"])
    assert total <= 3
    all_links = [i["link"] for _, items in appendix["groups"] for i in items]
    assert hero not in all_links and card not in all_links
    all_corpus = {hero, card, "https://s.example/v1", "https://s.example/s1",
                  "https://s.example/s2", "https://s.example/p1", "https://s.example/p2"}
    empty = TripOrchestrator._build_appendix(research, exclude_links=all_corpus)
    assert empty["groups"] == []
