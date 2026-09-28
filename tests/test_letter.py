from src.core.models import LetterContent, LetterMoment


def test_letter_shape():
    letter = LetterContent(
        subject="Creta",
        opening="La porta del van si apre sull'aria salata.",
        moments=[{"prose": "A Festo la luce taglia i muri color miele.",
                  "place_links": ["https://example.com/festo"]}],
        closing="Ne parliamo insieme.",
    )
    assert len(letter.moments) == 1
    assert letter.moments[0].place_links == ["https://example.com/festo"]


def test_letter_prompt_bans_inventory():
    from src.core.models import TripIntent
    from src.core.prompts import build_letter_prompt
    prompt = build_letter_prompt("mare e van", TripIntent(interests=["mare"]), "Festo — https://example.com/festo")
    # NOTE (replaces wrong-shaped tail in brief): the prompt must CITE
    # 'coppia (2)' as a banned bureaucratic format, not omit it.
    assert "coppia (2)" in prompt
    assert "per voi due" in prompt
    assert "possibile sosta" in prompt
    assert "prosa continua" in prompt
    assert "Festo — https://example.com/festo" in prompt
