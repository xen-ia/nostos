from src.core.models import DepartureAirports, ResolvedDestinations, TripIntent
from src.core.prompts import build_email_prompt, build_geo_prompt
from tests.fakes import FakeLLM, make_trip


async def test_fakellm_geo_defaults():
    llm = FakeLLM(response=TripIntent(destination="Tokyo"))
    resolved = await llm.extract("p", ResolvedDestinations)
    airports = await llm.extract("p", DepartureAirports)
    assert resolved == ResolvedDestinations(destinations=[], rationale="")
    assert airports == DepartureAirports(codes=[])


async def test_fakellm_geo_explicit_responses_win():
    resolved = ResolvedDestinations(destinations=[{"name": "Paros", "country": "Grecia"}], rationale="mare e relax")
    airports = DepartureAirports(codes=["MXP", "LIN"])
    llm = FakeLLM(
        response=TripIntent(),
        responses={ResolvedDestinations: resolved, DepartureAirports: airports},
    )
    assert await llm.extract("p", ResolvedDestinations) == resolved
    assert await llm.extract("p", DepartureAirports) == airports


def test_build_geo_prompt_includes_trip_context_and_rules():
    trip = make_trip(destination="Grecia", departure_location="Italy",
                     free_text="isole tranquille, lontano dalle folle")
    intent = TripIntent(interests=["mare"], style=["lontano dalle folle"], pace="rilassato")
    prompt = build_geo_prompt(trip, intent)
    assert "Grecia" in prompt
    assert "Italy" in prompt
    assert "isole tranquille, lontano dalle folle" in prompt
    assert "The rationale MUST be written in ITALIAN." in prompt
    assert "max 4" in prompt.lower()


def test_build_email_prompt_focus_line_omitted_when_empty():
    trip = make_trip(stay_preference="agriturismo")
    intent = TripIntent(destination="Tokyo")
    prompt = build_email_prompt(intent, "flights", "pois", "stays", trip)
    assert "Focus scelto dal sistema" not in prompt
    assert (
        "    Stay preference: agriturismo\n\n    USER FREE TEXT (verbatim):"
        in prompt
    )
    assert "\n\n\n" not in prompt


def test_build_email_prompt_focus_line_rendered_when_given():
    trip = make_trip(stay_preference="agriturismo")
    intent = TripIntent(destination="Tokyo")
    prompt = build_email_prompt(intent, "flights", "pois", "stays", trip,
                                resolve_rationale="mete scelte per mare e quiete")
    assert (
        "    Stay preference: agriturismo\n"
        "\n"
        "    Focus scelto dal sistema: mete scelte per mare e quiete\n"
        "\n"
        "    USER FREE TEXT (verbatim):"
    ) in prompt
