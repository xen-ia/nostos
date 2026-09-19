# tests/test_email_restructure_a.py — Part A (backend) of the email restructure.
import pytest

from src.core.models import Curation, ResolvedDestinations, TripIntent
from src.core.orchestrator import TripOrchestrator
from src.core.prompts import build_curation_prompt
from tests.fakes import FakeDatabase, FakeEmailSender, FakeLLM, make_store, make_trip

from tests.test_orchestrator import EMAIL


def _van_intent(**overrides):
    base = dict(destination="Crete", interests=[], style=["lento"],
                travel_mode="van_life", accommodation_style="van")
    base.update(overrides)
    return TripIntent(**base)


# --- A1: curation graceful degradation (prompt level) ---

def test_curation_prompt_empty_interests_falls_back_to_mode_and_destination():
    prompt = build_curation_prompt(make_trip(), _van_intent(), "corpus")
    assert "travel_mode" in prompt
    assert "accommodation_style" in prompt
    assert "destination" in prompt
    # fallback is explicit: empty interests -> match on mode/style/destination
    assert "empty" in prompt.lower()


def test_curation_prompt_states_poi_failure_rule():
    intent = TripIntent(interests=["mare"], style=["lento"], pace="rilassato")
    prompt = build_curation_prompt(make_trip(), intent, "corpus")
    assert "An email with a non-empty maps corpus and zero POI picks is a failure" in prompt
    assert "prefer" in prompt and "fitting POI" in prompt
    # zero-valid escape kept
    assert "Zero items in a category is a valid choice when nothing fits." in prompt


def test_curation_prompt_interest_match_only_when_interests_exist():
    with_interests = build_curation_prompt(
        make_trip(), TripIntent(interests=["mare"]), "corpus")
    assert "stated interest" in with_interests
    without_interests = build_curation_prompt(
        make_trip(), TripIntent(interests=[]), "corpus")
    assert "stated interest" not in without_interests


# --- A4: van-compatible stays policy (prompt level) ---

def test_curation_prompt_van_stays_policy():
    prompt = build_curation_prompt(make_trip(), _van_intent(), "corpus").lower()
    assert "campsite" in prompt or "campeggio" in prompt or "campsites" in prompt
    assert "rental" in prompt
    assert "plain hotels are not stays-picks" in prompt
    assert "stays section is absent" in prompt


# --- A2: rationale logging (orchestrator level) ---

async def test_curated_rationale_stored_in_package(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(
        response=TripIntent(destination="Tokyo", interests=["cibo"]),
        email_response=EMAIL,
        responses={Curation: Curation(
            flight_indices=[0], poi_indices=[0], stay_indices=[0],
            rationale="Scelti per cibo locale e ritmo lento")},
    )

    async def fake_flights(*a, **k):
        return [{"airline": "ANA", "from": "MXP", "to": "HND",
                 "departure_date": "2026-09-01", "price_eur": 320,
                 "link": "https://example.com/flight"}]

    async def fake_maps(query, **k):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7,
                 "link": "https://example.com/poi"}]

    async def fake_places(**k):
        return [{"name": "Ryokan X", "price_per_night_eur": 95,
                 "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    db = FakeDatabase()
    orch = TripOrchestrator(store=store, llm_client=llm,
                            email_sender=FakeEmailSender(), database=db,
                            trip_id=trip.id)
    await orch.run()

    assert db.saved, "trip should complete"
    assert db.saved[0]["package"]["curated_rationale"] == \
        "Scelti per cibo locale e ritmo lento"


# --- A3: van rental research (orchestrator level) ---

async def _execute(monkeypatch, intent, destination="Crete", places_impl=None):
    trip = make_trip(destination=destination)
    store = make_store()
    await store.create(trip)
    orch = TripOrchestrator(store=store, llm_client=FakeLLM(response=intent),
                            email_sender=FakeEmailSender(),
                            database=FakeDatabase(), trip_id=trip.id)
    calls = []

    async def fake_places(**kwargs):
        calls.append(kwargs)
        if places_impl is not None:
            return places_impl(kwargs)
        return [{"name": "Stay X", "price_per_night_eur": 50,
                 "link": "https://example.com/stay"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "POI", "type": "Beach", "rating": 4.5,
                 "link": "https://example.com/poi"}]

    async def fake_flights(*a, **k):
        return []

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    tool_calls: list[dict] = []
    result = await orch._execute_searches(
        trip, intent, [], [("2026-09-01", "2026-09-10")],
        [{"name": "POI", "type": "Beach", "rating": 4.5,
          "link": "https://example.com/poi"}],
        tool_calls, resolved=ResolvedDestinations(destinations=[], rationale=""),
        departure_codes=[])
    return result, tool_calls, calls


async def test_rental_query_issued_only_for_van(monkeypatch):
    result, tool_calls, calls = await _execute(monkeypatch, _van_intent())

    rental_calls = [c for c in calls
                    if (c.get("query") or "").startswith("noleggio camper van")]
    assert len(rental_calls) == 1
    assert rental_calls[0]["query"] == "noleggio camper van Crete"
    # same check-in/out as the main stays query
    assert rental_calls[0]["check_in_date"] == calls[0]["check_in_date"]
    assert rental_calls[0]["check_out_date"] == calls[0]["check_out_date"]
    # tool_calls entry with rental marker
    rental_tc = [tc for tc in tool_calls
                 if tc.get("params", {}).get("rental") is True]
    assert len(rental_tc) == 1
    # results tagged into the places corpus
    rentals = [p for p in result["corpus"]["places"] if p.get("rental") is True]
    assert rentals, "rental results must be tagged into the places corpus"
    assert all("link" in p and "name" in p for p in rentals)


async def test_rental_query_triggered_by_travel_mode_alone(monkeypatch):
    intent = _van_intent(accommodation_style="camping", travel_mode="van_life")
    _, _, calls = await _execute(monkeypatch, intent)
    assert any((c.get("query") or "").startswith("noleggio camper van")
               for c in calls)


async def test_no_rental_query_for_non_van(monkeypatch):
    intent = TripIntent(destination="Crete", interests=["mare"],
                        travel_mode="fixed", accommodation_style="hotel")
    _, tool_calls, calls = await _execute(monkeypatch, intent)
    assert not any((c.get("query") or "").startswith("noleggio camper van")
                   for c in calls)
    assert not any(tc.get("params", {}).get("rental") is True
                   for tc in tool_calls)


async def test_no_rental_query_without_destination(monkeypatch):
    result, tool_calls, calls = await _execute(
        monkeypatch, _van_intent(destination=None), destination=None)
    assert not any(tc.get("params", {}).get("rental") is True
                   for tc in tool_calls)
    assert not any((c.get("query") or "").startswith("noleggio camper van")
                   for c in calls)
