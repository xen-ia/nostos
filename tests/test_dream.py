from src.core.dream import find_new_proper_nouns, is_generic_scene


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


def test_letter_places_omits_missing_price():
    """Price gate (letter places list): no 'None ...' strings ever reach the email."""
    from src.core.orchestrator import TripOrchestrator
    curated = {
        "flights": [],
        "maps": [{"name": "Festo", "link": "https://example.com/festo"}],
        "places": [{"name": "Campeggio X", "price_per_night_eur": None,
                    "link": "https://example.com/c"}],
    }
    moments = [{"prose": "x", "place_links": ["https://example.com/c"]}]
    out = TripOrchestrator._letter_places(curated, moments)
    assert "None" not in str(out)
    assert any(p["name"] == "Campeggio X" for p in out)


def test_find_new_proper_nouns_ignores_sentence_starts():
    from src.core.dream import find_new_proper_nouns
    assert find_new_proper_nouns("Poi si va al mare. Il sole splende.", []) == []
    assert find_new_proper_nouns("Da Festo si va a Balos in barca.", ["festo"]) == ["Balos"]
