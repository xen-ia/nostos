from src.core.dream import find_new_proper_nouns, is_generic_scene
from src.core.models import DreamContent, DreamScene


def test_is_generic_scene():
    assert is_generic_scene("Una possibile sosta per il van lungo il percorso.")
    assert is_generic_scene("Bello, incantevole, meraviglioso.")
    assert is_generic_scene("Corto.")
    assert not is_generic_scene(
        "A Elafonissi l'acqua bassa di ottobre sa di sale e resina dei ginepri.")


def test_find_new_proper_nouns():
    known = ["Palazzo Minoico di Festo", "Grammeno Camping"]
    assert find_new_proper_nouns("Da Festo si va a Balos in barca.", known) == ["Balos"]
    assert find_new_proper_nouns("Da Festo si torna a Festo.", known) == []
    assert find_new_proper_nouns("il mare è calmo.", known) == []


def test_dream_content_min_two_scenes_shape():
    d = DreamContent(subject="Creta", arrival="Atterri la sera.",
                     scenes=[{"title": "A", "prose": "testo lungo a sufficienza per passare il gate"},
                             {"title": "B", "prose": "y"}])
    assert len(d.scenes) == 2


def test_dream_prompt_has_three_acts_and_bans():
    from src.core.prompts import build_dream_prompt
    from src.core.models import TripIntent
    p = build_dream_prompt("VIAGGIO", TripIntent(interests=["mare"]), "F", "M", "P", 30)
    assert "Atto I" in p and "Atto II" in p and "Atto III" in p
    assert "possibile sosta" in p and "incantevole" in p
    assert "2 scene" in p or "2 o 3" in p


def test_render_places_omits_missing_price():
    """Price gate (dream prompt blocks): no 'None ...' strings ever reach prompts."""
    from src.core.orchestrator import TripOrchestrator
    out = TripOrchestrator._render_places(
        [{"name": "Campeggio X", "price_per_night_eur": None, "link": "https://example.com/c"}],
        numbered=True,
    )
    assert "None" not in out
    assert "Campeggio X" in out


def test_render_flights_omits_missing_price():
    from src.core.orchestrator import TripOrchestrator
    out = TripOrchestrator._render_flights(
        [{"airline": "A", "from": "MXP", "to": "AAA", "departure_date": "2026-09-01",
          "price_eur": None, "link": "https://example.com/f"}],
        numbered=True,
    )
    assert "None" not in out
    assert "2026-09-01" in out


def test_find_new_proper_nouns_ignores_sentence_starts():
    from src.core.dream import find_new_proper_nouns
    assert find_new_proper_nouns("Poi si va al mare. Il sole splende.", []) == []
    assert find_new_proper_nouns("Da Festo si va a Balos in barca.", ["festo"]) == ["Balos"]
