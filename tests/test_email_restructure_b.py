"""Part B tests: grounded copy, elegant titles, rental section, backed-only appendix."""

from src.core.orchestrator import TripOrchestrator
from src.core.validation import build_allowed_resources, validate_resources
from src.services.apis.email import (
    _humanize_flight_name,
    build_html_email,
)

BASE = {"opening": "O.", "understanding": "U.", "resources": [], "cta": "C.",
        "honest_note": "N.", "sections_map": {}, "appendix": {"groups": [], "source_links": []}}

OLD_PROMISES = (
    "rifornire acqua", "scaricare", "soste per il pranzo", "Dormi nel veicolo",
    "porti di imbarco", "ancoraggi sicuri", "pernottamenti lungo il percorso",
    "deviare verso i luoghi", "rifornimenti ed esplorazioni",
)


# --- B1: no travel box in acts, grounded rental/appendix sections ---


def test_no_travel_box_in_html_or_text():
    bodies = ("Tappe giornaliere in auto, strada facendo.",
              "Itinerario su strada, pernottamenti a bordo.",
              "Rotte costiere in barca, tappe a terra.")
    for mode in ("road_trip", "van_life", "sailing"):
        html = build_html_email({**BASE, "travel_mode": mode})
        text = TripOrchestrator._compose_body_text({**BASE, "travel_mode": mode})
        for body in bodies:
            assert body not in html, (mode, body)  # travel box deleted with acts
            assert body not in text, (mode, body)


def test_static_mode_promises_gone_from_all_modes():
    for mode in ("road_trip", "van_life", "sailing"):
        html = build_html_email({**BASE, "travel_mode": mode})
        text = TripOrchestrator._compose_body_text({**BASE, "travel_mode": mode})
        for phrase in OLD_PROMISES:
            assert phrase not in html, (mode, phrase)
            assert phrase not in text, (mode, phrase)


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
    assert "easyJet · MXP – INV" in html  # hero logistics, humanized, no doubled Volo
    assert "Ryanair Bergamo – Edimburgo" in html  # second flight logistics
    body = html.split("</head>", 1)[-1]
    assert "MXP ->" not in body and "Bergamo →" not in body
    assert "departure 2026-12-21" not in body
    assert html.count(f'href="{hero}"') == 1
    assert html.count('href="https://flights.example/other"') == 1


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
    assert "Hotel X" not in html  # unlinked stays render nowhere in acts (no phases)
    assert "https://rent.example/a" in after


def test_rental_section_absent_for_non_van_and_without_rentals():
    rental = _rental("https://rent.example/a")
    # non-van trip: no rental section, unlinked rental renders nowhere (orphan rule)
    html = build_html_email(_van_content([rental], travel_mode="fixed", accommodation_style="hotel"))
    assert "Dove noleggiare" not in html
    assert "Van Rent X" not in html
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
    # single Apri link per card: exactly one rental card rendered once
    assert html.count("https://rent.example/a") == 1


def test_validate_resources_covers_rental_tagged_places():
    place = {**_rental("https://rent.example/a"), "rental": True}
    allowed = build_allowed_resources([], [], [place])
    report = validate_resources([dict(place)], allowed)
    assert len(report.valid) == 1 and not report.invalid


def test_body_text_mirrors_rental_section():
    content = _van_content([_hotel(), _rental("https://rent.example/a")])
    content["arrival"] = "Atterri la sera."
    content["scenes"] = [
        {"title": "Sera", "prose": "Luci calde e sale.", "place_links": []},
    ]
    text = TripOrchestrator._compose_body_text(content)
    assert "Dove noleggiare il van:" in text
    assert text.index("Sera") < text.index("Dove noleggiare il van:")
    after = text.split("Dove noleggiare il van:", 1)[-1]
    assert "https://rent.example/a" in after
    assert "Van Rent X" in after and "80 EUR" in after
    assert "L'itinerario:" not in text  # phases gone with the acts template


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
