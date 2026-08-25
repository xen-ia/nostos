from src.core.models import Curation, PeriodPlan, TargetQueries, TripIntent
from tests.fakes import FakeLLM


async def test_fakellm_returns_model_specific_responses():
    llm = FakeLLM(response=TripIntent(destination="Tokyo"))
    plan = await llm.extract("p", PeriodPlan)
    tgt = await llm.extract("p", TargetQueries)
    cur = await llm.extract("p", Curation)
    assert plan == PeriodPlan(windows=[])
    assert tgt == TargetQueries(queries=[])
    assert cur.flight_indices == [0, 1, 2] and cur.poi_indices == [0, 1, 2] and cur.stay_indices == [0, 1, 2]


async def test_fakellm_explicit_responses_win():
    plan = PeriodPlan(windows=[{"start": "2026-09-01", "end": "2026-09-30", "rationale": "shoulder season"}])
    llm = FakeLLM(response=TripIntent(), responses={PeriodPlan: plan})
    assert await llm.extract("p", PeriodPlan) == plan
