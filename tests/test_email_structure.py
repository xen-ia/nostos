# tests/test_email_structure.py
import re

from src.services.apis.email import build_html_email

BASE = {"opening": "O.", "understanding": "U.", "resources": [], "cta": "C.",
        "honest_note": "N.", "sections_map": {}, "appendix": {"groups": [], "source_links": []}}


def test_no_details_no_block_only_anchors():
    html = build_html_email({**BASE, "travel_mode": "van_life", "mobility": ["auto", "van"],
                             "feedback_link": "https://x.example/f?trip_id=1&token=abc"})
    assert "<details" not in html
    assert "Lascia un feedback" in html
    assert "https://x.example/f?trip_id=1&amp;token=abc" in html


def test_van_mobility_merged_single_line():
    html = build_html_email({**BASE, "travel_mode": "van_life", "mobility": ["auto", "van"]})
    assert html.count("Mezzi") == 1
    assert "Come spostarti" not in html


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
    html = build_html_email({**CARD_CONTENT, "reply_to": "a@b.c",
                             "feedback_link": "https://x.example/f"})
    # No anchor may contain another anchor anywhere in the email.
    assert not re.search(r"<a\b[^>]*>(?:(?!</a>).)*<a\b", html, re.S | re.I)
    # Card exposes exactly the title link + the Apri link as siblings.
    cards = re.findall(r'<table class="card-frame".*?</table>', html, re.S)
    assert len(cards) == 1
    assert len(re.findall(r"<a\b", cards[0])) == 2
    assert "Hotel X" in cards[0] and "Apri &rarr;" in cards[0]


def test_reply_button_wired_and_omitted_when_empty():
    with_reply = build_html_email({**BASE, "reply_to": "sender@example.com",
                                   "feedback_link": "https://x.example/f"})
    assert "Rispondi per continuare" in with_reply
    assert "mailto:sender@example.com" in with_reply
    without = build_html_email({**BASE, "feedback_link": "https://x.example/f"})
    assert "Rispondi per continuare" not in without
    assert "mailto:" not in without


def test_no_empty_button_cells():
    both = build_html_email({**BASE, "reply_to": "a@b.c",
                             "feedback_link": "https://x.example/f"})
    assert both.count('class="btn-cell"') == 2
    single = build_html_email({**BASE, "feedback_link": "https://x.example/f"})
    assert single.count('class="btn-cell"') == 1
    assert "Lascia un feedback" in single
    none = build_html_email({**BASE})
    assert 'class="btn-cell"' not in none
    assert "Lascia un feedback" not in none
    assert "Rispondi per continuare" not in none
