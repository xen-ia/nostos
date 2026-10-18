from src.core.models import DepartureAirports, ResolvedDestinations, TripIntent
from src.core.prompts import build_geo_prompt
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
