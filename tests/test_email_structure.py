# tests/test_email_structure.py
import re

from src.core.orchestrator import TripOrchestrator
from src.core.models import TripIntent
from src.core.prompts import build_curation_prompt
from src.services.apis.email import SITE_URL, build_html_email
from tests.fakes import make_trip

BASE = {"opening": "O.", "resources": [], "cta": "C.",
        "honest_note": "N.", "sections_map": {}, "appendix": {"groups": [], "source_links": []}}


def test_no_details_no_block_only_anchors():
    html = build_html_email({**BASE, "travel_mode": "van_life", "mobility": ["auto", "van"],
                             "feedback_link": "https://x.example/f?trip_id=1&token=abc"})
    assert "<details" not in html
    assert "Parliamone insieme" in html
    assert "https://x.example/f?trip_id=1&amp;token=abc" in html


def test_van_life_has_no_travel_box_but_keeps_rental():
    content = {**BASE, "travel_mode": "van_life", "mobility": ["auto", "van"],
               "resources": [{"name": "Van Rent X", "description": "Noleggio van fronte mare",
                              "price": "80 EUR", "link": "https://rent.example/a", "rental": True}],
               "sections_map": {"places": ["https://rent.example/a"]},
               "accommodation_style": "van"}
    html = build_html_email(content)
    assert "Mezzi" not in html
    assert "Vita in van" not in html  # travel box deleted with the acts template
    assert "Dove noleggiare il van" in html  # rental section stays


def test_cta_targets_min_44px():
    html = build_html_email({**BASE, "feedback_link": "https://x.example/f"})
    pads = re.findall(r"padding:(\d+)px", html)
    cta_pads = [int(p) for p in pads]
    assert cta_pads and min(cta_pads) >= 14  # 14px vertical padding ≈ 44px target with 16px text


MOMENT_CONTENT = {**BASE,
                  "opening": "Sbarchi la sera.",
                  "resources": [{"name": "Hotel X", "description": "",
                                 "price": "100 EUR", "link": "https://h.example/x"},
                                {"name": "Taverna Y", "description": "",
                                 "price": "", "link": "https://y.example/t"}],
                  "sections_map": {"maps": ["https://h.example/x", "https://y.example/t"]},
                  "moments": [
                      {"prose": "Luci calde e sale.",
                       "place_links": ["https://h.example/x"]},
                      {"prose": "Cucina vera e mare.",
                       "place_links": ["https://y.example/t"]},
                  ]}


def test_moments_use_sibling_anchors_no_nesting():
    content = {**MOMENT_CONTENT, "feedback_link": "https://x.example/f"}
    html = build_html_email(content)
    # No anchor may contain another anchor anywhere in the email.
    assert not re.search(r"<a\b[^>]*>(?:(?!</a>).)*<a\b", html, re.S | re.I)
    # Each moment exposes exactly one action link (prose is plain text, no boxes).
    assert html.count('href="https://h.example/x"') == 1  # moment one only
    assert html.count('href="https://y.example/t"') == 1  # moment two only
    assert "Taverna Y" not in html  # resource names never render, only moment prose
    assert "Luci calde" in html and "Vedi →" in html
    assert '<table class="card-frame"' not in html


def test_reply_gone_in_all_modes():
    with_link = build_html_email({**BASE, "feedback_link": "https://x.example/f"})
    assert "Rispondi per continuare" not in with_link
    assert "mailto:" not in with_link
    assert "Parliamone insieme" in with_link
    without_link = build_html_email({**BASE})
    assert "Rispondi per continuare" not in without_link
    assert "mailto:" not in without_link
    assert "Parliamone insieme" not in without_link


def test_no_empty_button_cells():
    single = build_html_email({**BASE, "feedback_link": "https://x.example/f"})
    assert single.count('class="btn-cell"') == 1
    assert "Parliamone insieme" in single
    none = build_html_email({**BASE})
    assert 'class="btn-cell"' not in none
    assert "Parliamone insieme" not in none
    assert "Rispondi per continuare" not in none
    assert "mailto:" not in none


def test_cta_copy_is_one_way():
    from src.core.orchestrator import CTA
    assert CTA == "Il prossimo passo è umano: dimmi cosa cambiare e ne parliamo insieme."
    html = build_html_email({**BASE, "cta": CTA,
                             "feedback_link": "https://x.example/f"})
    assert "IL TUO PARERE" in html.upper()
    assert "IL PROSSIMO PASSO È UMANO" in html.upper()
    assert "rispondi" not in html.lower()


def test_moment_renders_prose_with_single_vedi_link():
    link = "https://flights.example/abc"
    maps_link = "https://maps.example/taverna"
    content = {
        **BASE,
        "resources": [{"name": "Volo easyJet · Milano – Inverness", "description": "",
                       "price": "196 EUR", "link": link},
                      {"name": "Taverna X", "description": "",
                       "price": "", "link": maps_link}],
        "sections_map": {"flights": [link], "maps": [maps_link]},
        "moments": [{"prose": "Cucina vera e mare calmo.",
                    "place_links": [maps_link]}],
        "places": [{"name": "Volo easyJet · Milano – Inverness", "price": "196 EUR", "link": link},
                   {"name": "Taverna X", "price": "", "link": maps_link}],
    }
    html = build_html_email(content)
    assert "Cucina vera" in html  # moment renders
    assert "Come arrivare" not in html  # no arrival hero block anymore
    assert "I luoghi" in html and "196 EUR" in html  # places list carries flight + price
    assert '<table class="card-frame"' not in html  # flight never a grouped card
    assert html.count(f'href="{maps_link}"') == 2  # moment Vedi + places list vedi
    assert html.count(f'href="{link}"') == 1  # places list only
    cards = re.findall(r'<table class="card-frame".*?</table>', html, re.S)
    assert all(link not in card for card in cards)


def test_flight_links_live_only_in_places_list():
    hero = "https://flights.example/hero"
    other = "https://flights.example/other"
    content = {
        **BASE,
        "resources": [
            {"name": "Volo easyJet · Milano – Inverness", "description": "", "price": "",
             "link": hero},
            {"name": "Volo Ryanair · Bergamo – Edimburgo", "description": "", "price": "",
             "link": other},
        ],
        "sections_map": {"flights": [hero, other]},
        "moments": [{"prose": "Luci calde e sale.", "place_links": []}],
        "places": [{"name": "Volo easyJet · Milano – Inverness", "price": "", "link": hero},
                   {"name": "Volo Ryanair · Bergamo – Edimburgo", "price": "", "link": other}],
    }
    html = build_html_email(content)
    assert "L'itinerario" not in html  # phases gone with the letter template
    assert other in html
    assert html.count(f'href="{hero}"') == 1  # places list only, never a stop
    assert '<table class="card-frame"' not in html  # no box grid anymore


def test_raw_flight_name_humanized_and_price_deduped():
    from src.services.apis.email import _render_card
    hero = "https://flights.example/hero"
    other = "https://flights.example/other"
    hero_html = _render_card(
        {"name": "easyJet, MXP -> INV, departure 2026-12-21 10:35, 196 EUR",
         "description": "Partenza 2026-12-21, 196 EUR tutto incluso",
         "price": "196 EUR", "link": hero},
        is_flight=True)
    assert "departure 2026-12-21" not in hero_html
    assert "easyJet · MXP – INV" in hero_html
    assert hero_html.count("196 EUR") == 1  # price pill only, description duplicate stripped
    other_html = _render_card(
        {"name": "Ryanair, BGY -> EDI, departure 2026-12-21 07:00, 250 EUR",
         "description": "Alba a Edimburgo, 250 EUR con bagaglio",
         "price": "250 EUR", "link": other},
        is_flight=True)
    assert "Ryanair · BGY – EDI" in other_html
    assert other_html.count("250 EUR") == 1


def test_footer_url_single_occurrence():
    html = build_html_email({**BASE})
    assert html.count(SITE_URL) == 1


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
