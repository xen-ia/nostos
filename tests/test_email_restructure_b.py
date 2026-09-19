"""Part B tests: grounded copy, elegant titles, rental section, backed-only appendix."""
import re

from src.core.orchestrator import TripOrchestrator
from src.core.models import TripIntent
from src.core.prompts import build_email_prompt
from src.core.validation import build_allowed_resources, validate_resources
from src.services.apis.email import (
    _TRAVEL_MODE_BLOCKS,
    _humanize_flight_name,
    build_html_email,
)
from tests.fakes import make_trip

BASE = {"opening": "O.", "understanding": "U.", "resources": [], "cta": "C.",
        "honest_note": "N.", "sections_map": {}, "appendix": {"groups": [], "source_links": []}}

OLD_PROMISES = (
    "rifornire acqua", "scaricare", "soste per il pranzo", "Dormi nel veicolo",
    "porti di imbarco", "ancoraggi sicuri", "pernottamenti lungo il percorso",
    "deviare verso i luoghi", "rifornimenti ed esplorazioni",
)


# --- B1: neutral one-liners, grounded travel paragraph ---

def test_travel_mode_blocks_are_neutral_one_liners():
    assert _TRAVEL_MODE_BLOCKS["van_life"] == ("Vita in van", "Itinerario su strada, pernottamenti a bordo.")
    assert _TRAVEL_MODE_BLOCKS["road_trip"] == ("Come muoversi in loco", "Tappe giornaliere in auto, strada facendo.")
    assert _TRAVEL_MODE_BLOCKS["sailing"] == ("Navigazione", "Rotte costiere in barca, tappe a terra.")


def test_travel_box_and_text_mirror_use_neutral_one_liners():
    for mode, body in (("road_trip", "Tappe giornaliere in auto, strada facendo."),
                       ("van_life", "Itinerario su strada, pernottamenti a bordo."),
                       ("sailing", "Rotte costiere in barca, tappe a terra.")):
        html = build_html_email({**BASE, "travel_mode": mode})
        assert body in html
        text = TripOrchestrator._compose_body_text({**BASE, "travel_mode": mode})
        assert body in text


def test_static_mode_promises_gone_from_all_modes():
    for mode in ("road_trip", "van_life", "sailing"):
        html = build_html_email({**BASE, "travel_mode": mode})
        text = TripOrchestrator._compose_body_text({**BASE, "travel_mode": mode})
        for phrase in OLD_PROMISES:
            assert phrase not in html, (mode, phrase)
            assert phrase not in text, (mode, phrase)


def test_travel_paragraph_grounded_rule_in_prompt():
    intent = TripIntent(interests=["mare"], style=["lento"], pace="rilassato")
    prompt = build_email_prompt(intent, "none", "none", "none", trip=make_trip())
    assert ("The travel paragraph may name ONLY places present in RESOURCES; "
            "never invent services (water, drains, fuel, rentals).") in prompt


# --- B2: elegant flight titles ---

def test_humanize_raw_flight_line_is_elegant():
    out = _humanize_flight_name("easyJet, MXP -> INV, departure 2026-12-21 10:35, 196 EUR")
    assert out == "Volo easyJet · MXP – INV"
    assert "departure" not in out


def test_humanize_normalizes_arrows_in_titles():
    assert _humanize_flight_name("Volo Ryanair Bergamo → Edimburgo") == "Volo Ryanair Bergamo – Edimburgo"
    assert _humanize_flight_name("Volo easyJet Milano -> Inverness") == "Volo easyJet Milano – Inverness"
    elegant = "Volo easyJet · Milano – Inverness"
    assert _humanize_flight_name(elegant) == elegant


def test_no_arrows_in_rendered_flight_names():
    hero = "https://flights.example/hero"
    content = {
        **BASE,
        "resources": [
            {"name": "easyJet, MXP -> INV, departure 2026-12-21 10:35, 196 EUR",
             "description": "Diretto", "price": "196 EUR", "link": hero},
            {"name": "Volo Ryanair Bergamo → Edimburgo",
             "description": "", "price": "", "link": "https://flights.example/other"},
        ],
        "sections_map": {"flights": [hero, "https://flights.example/other"]},
    }
    html = build_html_email(content)
    names = re.findall(r'd-name"[^>]*>\s*<a[^>]*>(.*?)</a>', html, re.S)
    assert len(names) == 2  # hero title + grouped card title
    for name in names:
        assert "->" not in name and "→" not in name


def test_email_prompt_flight_name_rule_is_elegant():
    intent = TripIntent(interests=["mare"], style=["lento"], pace="rilassato")
    prompt = build_email_prompt(intent, "x", "y", "z", trip=make_trip())
    assert "Volo {airline} · {from} – {to}" in prompt
    flight_line = next(line for line in prompt.splitlines() if "Volo {airline}" in line)
    assert "->" not in flight_line and "→" not in flight_line


# --- B3: route logic for road/van trips ---

def _intent(mode):
    return TripIntent(interests=["mare"], style=["lento"], pace="rilassato", travel_mode=mode)


PLACES_TWO = ("[P0] Campeggio X — 20 EUR/night — https://p0.example\n"
              "[P1] Noleggio Y — 50 EUR/night — https://p1.example")


def test_route_rule_present_for_road_van_with_two_places():
    for mode in ("road_trip", "van_life"):
        prompt = build_email_prompt(_intent(mode), "none", "[M0] Spiaggia — https://m0.example",
                                    PLACES_TWO, trip=make_trip())
        assert "giorno 1-2" in prompt
        assert "grounded ONLY in the picked POI/stay resources" in prompt


def test_route_rule_counts_pois_and_stays_together():
    maps_two = "[M0] Spiaggia — https://m0.example\n[M1] Borgo — https://m1.example"
    prompt = build_email_prompt(_intent("road_trip"), "none", maps_two,
                                "no accommodations available", trip=make_trip())
    assert "giorno 1-2" in prompt


def test_route_rule_silent_otherwise():
    # fixed mode with plenty of places: silent
    prompt = build_email_prompt(_intent("fixed"), "none", "[M0] X — https://m0.example",
                                PLACES_TWO, trip=make_trip())
    assert "giorno 1-2" not in prompt
    # road trip with a single place: silent
    prompt = build_email_prompt(_intent("road_trip"), "none", "no points of interest",
                                "[P0] Solo — https://p0.example", trip=make_trip())
    assert "giorno 1-2" not in prompt
    # road trip with nothing: silent
    prompt = build_email_prompt(_intent("road_trip"), "no flights available",
                                "no points of interest", "no accommodations available",
                                trip=make_trip())
    assert "giorno 1-2" not in prompt


# --- B4: "Dove noleggiare" rental section ---

def _rental(link, name="Van Rent X"):
    return {"name": name, "description": "Noleggio van fronte mare", "price": "80 EUR",
            "link": link, "rental": True}


def _hotel(link="https://hotel.example/x"):
    return {"name": "Hotel X", "description": "Sul lungomare", "price": "100 EUR", "link": link}


def _van_content(resources, travel_mode="van_life", accommodation_style="van"):
    links = [r["link"] for r in resources]
    return {**BASE, "resources": resources,
            "sections_map": {"places": links},
            "travel_mode": travel_mode, "accommodation_style": accommodation_style}


def test_rental_section_renders_for_van_only():
    html = build_html_email(_van_content([_hotel(), _rental("https://rent.example/a")]))
    before, after = html.split("Dove noleggiare il van")
    assert "Van Rent X" not in before and "Van Rent X" in after
    assert "Hotel X" in before  # stays keep their own group
    assert "https://rent.example/a" in after


def test_rental_section_absent_for_non_van_and_without_rentals():
    rental = _rental("https://rent.example/a")
    # non-van trip: rental stays a normal "Dove stare" card, no rental section
    html = build_html_email(_van_content([rental], travel_mode="fixed", accommodation_style="hotel"))
    assert "Dove noleggiare" not in html
    assert "Van Rent X" in html and "Dove stare" in html
    # van trip without rentals: no section
    html = build_html_email(_van_content([_hotel()]))
    assert "Dove noleggiare" not in html


def test_rental_section_triggers_on_accommodation_style_alone():
    html = build_html_email(_van_content([_rental("https://rent.example/a")],
                                         travel_mode="fixed", accommodation_style="van"))
    assert "Dove noleggiare il van" in html


def test_rental_section_caps_at_two_cards():
    rentals = [_rental(f"https://rent.example/{i}", name=f"Van Rent {i}") for i in range(3)]
    html = build_html_email(_van_content(rentals))
    assert "Van Rent 0" in html and "Van Rent 1" in html
    assert "Van Rent 2" not in html


def test_rentals_never_duplicated_between_sections():
    html = build_html_email(_van_content([_hotel(), _rental("https://rent.example/a")]))
    # title link + "Apri" link per card: exactly one card for the rental
    assert html.count("https://rent.example/a") == 2


def test_validate_resources_covers_rental_tagged_places():
    place = {**_rental("https://rent.example/a"), "rental": True}
    allowed = build_allowed_resources([], [], [place])
    report = validate_resources([dict(place)], allowed)
    assert len(report.valid) == 1 and not report.invalid


def test_body_text_mirrors_rental_section():
    text = TripOrchestrator._compose_body_text(
        _van_content([_hotel(), _rental("https://rent.example/a")]))
    assert "Dove noleggiare il van:" in text
    after = text.split("Dove noleggiare il van:", 1)[-1]
    assert "https://rent.example/a" in after
    punti = text.split("Punti di partenza:", 1)[-1].split("Dove noleggiare", 1)[0]
    assert "Van Rent X" not in punti and "Hotel X" in punti


# --- B5: appendix only-backed ---

def _b5_research():
    return {"corpus": {
        "flights": [{"airline": "A", "link": "https://shown-flight.example"},
                    {"airline": "B", "link": "https://random-flight.example"}],
        "places": [{"name": "Shown Hotel", "link": "https://shown-hotel.example"},
                   {"name": "Random House", "link": "https://random-house.example"},
                   {"name": "Curated Stay", "link": "https://curated-unshown.example"}],
        "maps": [{"name": "Shown POI", "link": "https://shown-poi.example"},
                 {"name": "Random POI", "link": "https://random-poi.example"},
                 {"name": "Junk", "link": "https://www.youtube.com/watch?v=x"}],
    }}


_B5_SHOWN = {"https://shown-flight.example", "https://shown-hotel.example", "https://shown-poi.example"}
_B5_ALLOWED = _B5_SHOWN | {"https://curated-unshown.example", "https://www.youtube.com/watch?v=x"}


def test_build_appendix_only_backed_links():
    appendix = TripOrchestrator._build_appendix(_b5_research(), exclude_links=set(_B5_SHOWN),
                                                allowed_links=set(_B5_ALLOWED))
    all_links = [i["link"] for _, items in appendix["groups"] for i in items]
    assert "https://curated-unshown.example" in all_links
    for random_link in ("https://random-flight.example", "https://random-house.example",
                        "https://random-poi.example"):
        assert random_link not in all_links
    assert "https://www.youtube.com/watch?v=x" not in all_links  # still junk-filtered
    assert sum(len(items) for _, items in appendix["groups"]) <= 3


def test_build_appendix_without_allowlist_keeps_legacy_behavior():
    hero = "https://flights.example/hero"
    research = {"corpus": {
        "flights": [{"airline": "A", "link": hero}, {"airline": "B", "link": "https://s.example/v1"}],
        "places": [], "maps": [],
    }}
    appendix = TripOrchestrator._build_appendix(research, exclude_links={hero})
    all_links = [i["link"] for _, items in appendix["groups"] for i in items]
    assert "https://s.example/v1" in all_links and hero not in all_links


def test_body_text_fonti_only_backed():
    appendix = TripOrchestrator._build_appendix(_b5_research(), exclude_links=set(_B5_SHOWN),
                                                allowed_links=set(_B5_ALLOWED))
    content = {**BASE,
               "resources": [{"name": "Shown Hotel", "description": "", "price": "",
                              "link": "https://shown-hotel.example"}],
               "sections_map": {"places": ["https://shown-hotel.example"]},
               "appendix": appendix}
    text = TripOrchestrator._compose_body_text(content)
    after = text.split("Fonti:", 1)[-1]
    assert "https://curated-unshown.example" in after
    assert "https://random-house.example" not in after


# --- one-way product rule on new copy ---

def test_new_copy_is_one_way():
    html = build_html_email(_van_content([_hotel(), _rental("https://rent.example/a")]))
    assert "rispondi" not in html.lower()
    assert "mailto:" not in html
    prompt = build_email_prompt(_intent("road_trip"), "none", "[M0] X", PLACES_TWO, trip=make_trip())
    assert "rispondi" not in prompt.lower()
