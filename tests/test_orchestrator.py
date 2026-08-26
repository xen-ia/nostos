from src.core.models import Curation, EmailContent, PeriodPlan, TripIntent
from src.core.orchestrator import TripOrchestrator
from src.core.schemas import TripStatus
from tests.fakes import FakeDatabase, FakeEmailSender, FakeLLM, make_store, make_trip

INTENT = TripIntent(
    destination="Tokyo",
    departure_airport_code="MXP",
    destination_airport_code="HND",
    interests=["cibo"],
    style=["autentico"],
    pace="moderato",
)

EMAIL = EmailContent(
    subject="Il tuo viaggio a Tokyo",
    opening="Tokyo in settembre ha un che di magico.",
    understanding="Capisco che cerchi cibo locale lontano dalle folle.",
    resources=[{"name": "Senso-ji", "description": "Tempio storico", "price": "", "link": "https://example.com/poi"}],
)


async def _run(orchestrator):
    await orchestrator.run()


def _make_llm():
    return FakeLLM(response=INTENT, email_response=EMAIL)


async def test_happy_path_sends_email_and_saves_history(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = _make_llm()
    email = FakeEmailSender()
    db = FakeDatabase()

    async def fake_flights(*args, **kwargs):
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01", "price_eur": 320, "link": "https://example.com/flight"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    orchestrator = TripOrchestrator(
        store=store,
        llm_client=llm,
        email_sender=email,
        database=db,
        trip_id=trip.id,
    )
    await _run(orchestrator)

    assert len(email.sent) == 1
    assert email.sent[0]["to"] == "test@example.com"
    assert len(db.saved) == 1
    assert db.saved[0]["trip_id"] == trip.id

    got = await store.get(trip.id)
    assert got.status == TripStatus.DONE
    assert db.status.get(trip.id) == TripStatus.DONE.value
    assert await store.claim(trip.id, ttl_seconds=300) is True

    done_updates = [u for u in db.status_updates.get(trip.id, []) if u.get("status") == TripStatus.DONE.value]
    assert done_updates, f"expected a DONE update, got {db.status_updates}"
    assert done_updates[0]["send_datetime"], "send_datetime must be set on success"
    from datetime import datetime as dt

    assert isinstance(done_updates[0]["send_datetime"], dt), "send_datetime must be a datetime object (asyncpg needs it)"
    assert done_updates[0]["duration_seconds"] >= 0


async def test_happy_path_saves_model_in_history(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = _make_llm()
    email = FakeEmailSender()
    db = FakeDatabase()

    async def one(*args, **kwargs):
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01", "price_eur": 320, "link": "https://example.com/flight"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", one)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    orchestrator = TripOrchestrator(
        store=store,
        llm_client=llm,
        email_sender=email,
        database=db,
        trip_id=trip.id,
        llm_model="qwen3:30b-a3b-instruct-2507-q4_K_M",
    )
    await _run(orchestrator)

    assert db.saved[0]["model"] == "qwen3:30b-a3b-instruct-2507-q4_K_M"


async def test_all_searches_empty_aborts_without_email(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT)
    email = FakeEmailSender()
    db = FakeDatabase()

    async def empty(*args, **kwargs):
        return []

    monkeypatch.setattr("src.core.orchestrator.flights.search", empty)
    monkeypatch.setattr("src.core.orchestrator.maps.research", empty)
    monkeypatch.setattr("src.core.orchestrator.places.search", empty)

    orchestrator = TripOrchestrator(
        store=store,
        llm_client=llm,
        email_sender=email,
        database=db,
        trip_id=trip.id,
    )
    await _run(orchestrator)

    assert email.sent == []
    assert db.saved == []
    got = await store.get(trip.id)
    assert got.status == TripStatus.ERROR
    assert "No resources" in got.result
    assert await store.claim(trip.id, ttl_seconds=300) is True


async def test_serpapi_errors_abort_without_email(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT)
    email = FakeEmailSender()
    db = FakeDatabase()

    async def raise_error(*args, **kwargs):
        raise RuntimeError("serpapi down")

    monkeypatch.setattr("src.core.orchestrator.flights.search", raise_error)
    monkeypatch.setattr("src.core.orchestrator.maps.research", raise_error)
    monkeypatch.setattr("src.core.orchestrator.places.search", raise_error)

    orchestrator = TripOrchestrator(
        store=store,
        llm_client=llm,
        email_sender=email,
        database=db,
        trip_id=trip.id,
    )
    await _run(orchestrator)

    assert email.sent == []
    assert db.saved == []
    got = await store.get(trip.id)
    assert got.status == TripStatus.ERROR
    assert "all searches failed" in got.result


async def test_llm_error_marks_trip_error():
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT, error=RuntimeError("llm down"))
    email = FakeEmailSender()
    db = FakeDatabase()

    orchestrator = TripOrchestrator(
        store=store,
        llm_client=llm,
        email_sender=email,
        database=db,
        trip_id=trip.id,
    )
    await _run(orchestrator)

    got = await store.get(trip.id)
    assert got.status == TripStatus.ERROR
    assert got.result is not None
    assert db.status.get(trip.id) == TripStatus.ERROR.value
    assert await store.claim(trip.id, ttl_seconds=300) is True

    err_updates = [u for u in db.status_updates.get(trip.id, []) if u.get("status") == TripStatus.ERROR.value]
    assert err_updates, f"expected an ERROR update, got {db.status_updates}"
    assert err_updates[0]["error_message"], "error_message must be persisted on failure"


async def test_already_claimed_returns_without_side_effects():
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT)
    email = FakeEmailSender()
    db = FakeDatabase()

    await store.claim(trip.id, ttl_seconds=300)

    orchestrator = TripOrchestrator(
        store=store,
        llm_client=llm,
        email_sender=email,
        database=db,
        trip_id=trip.id,
    )
    await _run(orchestrator)

    assert email.sent == []
    assert db.saved == []
    got = await store.get(trip.id)
    assert got.status == TripStatus.PENDING


async def test_no_dates_triggers_period_plan_and_multi_window_flight_probe(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip(start_date=None, end_date=None))
    llm = FakeLLM(
        response=INTENT,
        email_response=EMAIL,
        responses={PeriodPlan: PeriodPlan(windows=[
            {"start": "2026-09-01", "end": "2026-09-15", "rationale": "mild"},
            {"start": "2026-10-01", "end": "2026-10-15", "rationale": "cheaper"},
        ])},
    )

    seen_outbound_dates = []

    async def fake_flights(departure, destination, start_date, end_date, **kwargs):
        seen_outbound_dates.append(start_date)
        price = 400 if start_date == "2026-09-01" else 300
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": start_date,
                 "price_eur": price, "link": f"https://example.com/{start_date}"}]

    stay_windows = []

    async def fake_places(**kwargs):
        stay_windows.append(kwargs.get("check_in_date"))
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    email = FakeEmailSender()
    db = FakeDatabase()
    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=email,
                                    database=db, trip_id=trip.id)
    await _run(orchestrator)

    assert sorted(seen_outbound_dates) == ["2026-09-01", "2026-10-01"]  # both windows probed
    assert stay_windows[-1] == "2026-10-01"  # stays aligned to cheapest window
    assert email.sent and db.saved  # trip completes


async def test_unusable_period_plan_falls_back(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip(start_date=None, end_date=None))
    llm = FakeLLM(response=INTENT, email_response=EMAIL)  # default PeriodPlan(windows=[])

    seen = []

    async def fake_flights(*args, **kwargs):
        seen.append(kwargs.get("outbound_date") or args[2])
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "x",
                 "price_eur": 300, "link": "https://example.com/f"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=FakeEmailSender(),
                                    database=FakeDatabase(), trip_id=trip.id)
    await _run(orchestrator)

    assert len(seen) == 1  # exactly the fallback window


async def test_start_only_trip_probes_one_way_flight_without_period_llm_call(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip(end_date=None))
    llm = FakeLLM(response=INTENT, email_response=EMAIL)

    flight_calls = []
    stay_kwargs = []

    async def fake_flights(*args, **kwargs):
        flight_calls.append((args, kwargs))
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01",
                 "price_eur": 320, "link": "https://example.com/f"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        stay_kwargs.append(kwargs)
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    email = FakeEmailSender()
    db = FakeDatabase()
    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=email,
                                    database=db, trip_id=trip.id)
    await _run(orchestrator)

    assert len(flight_calls) == 1  # exactly one probe
    args, _ = flight_calls[0]
    assert args[2] == "2026-09-01"  # outbound = trip start
    assert args[3] is None  # end_date=None -> one-way search (type=2)
    assert stay_kwargs[-1].get("check_out_date") is None  # stays fall back to default window
    assert all(model is not PeriodPlan for _, model in llm.calls)  # no period-planning LLM call
    assert email.sent and db.saved  # trip completes


async def test_stages_run_in_order_and_package_records_tool_calls(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT, email_response=EMAIL)
    order = []

    async def fake_flights(*args, **kwargs):
        order.append("flights")
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01",
                 "price_eur": 320, "link": "https://example.com/flight",
                 "_meta": {"google_flights_url": "https://gf.example"}}]

    async def fake_maps(query, **kwargs):
        order.append(f"maps:{query}")
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        order.append("places")
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    email = FakeEmailSender()
    db = FakeDatabase()
    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=email,
                                    database=db, trip_id=trip.id)
    await _run(orchestrator)

    assert order[0].startswith("maps:")          # explore first
    assert "places" in order and "flights" in order
    assert len(db.saved) == 1
    package = db.saved[0]["package"]
    assert package["tool_calls"], "every serpapi call must be logged"
    assert all(set(tc) == {"engine", "params", "result_count"} for tc in package["tool_calls"])
    assert "corpus" in package and "curated" in package


async def test_curation_indices_out_of_range_are_dropped(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(
        response=INTENT,
        email_response=EMAIL,
        responses={Curation: Curation(flight_indices=[99], poi_indices=[0], stay_indices=[0])},
    )

    async def fake_flights(*args, **kwargs):
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01",
                 "price_eur": 320, "link": "https://example.com/flight"}]

    async def fake_maps(*args, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    db = FakeDatabase()
    orchestrator = TripOrchestrator(store=store, llm_client=llm, email_sender=FakeEmailSender(),
                                    database=db, trip_id=trip.id)
    await _run(orchestrator)

    assert db.saved[0]["package"]["curated"]["flights"] == []      # index 99 dropped
    assert len(db.saved[0]["package"]["curated"]["maps"]) == 1


# --- Validation gate: grounding of EmailContent resources against the curated corpus ---

HALLUCINATED = {"name": "Castello Fantasma", "description": "Non esiste nel corpus",
                "price": "", "link": "https://fake.example/castello-fantasma"}


def _email(resources: list[dict]) -> EmailContent:
    return EmailContent(subject="Il tuo viaggio a Tokyo", opening="Tokyo in settembre ha un che di magico.",
                        understanding="Capisco che cerchi cibo locale lontano dalle folle.",
                        resources=resources)


async def _run_with_searches(monkeypatch, llm, email, db, trip, store):
    async def fake_flights(*args, **kwargs):
        return [{"airline": "ANA", "from": "MXP", "to": "HND", "departure_date": "2026-09-01",
                 "price_eur": 320, "link": "https://example.com/flight"}]

    async def fake_maps(query, **kwargs):
        return [{"name": "Senso-ji", "type": "Temple", "rating": 4.7, "link": "https://example.com/poi"}]

    async def fake_places(**kwargs):
        return [{"name": "Ryokan X", "price_per_night_eur": 95, "link": "https://example.com/hotel"}]

    monkeypatch.setattr("src.core.orchestrator.flights.search", fake_flights)
    monkeypatch.setattr("src.core.orchestrator.maps.research", fake_maps)
    monkeypatch.setattr("src.core.orchestrator.places.search", fake_places)

    orchestrator = TripOrchestrator(llm_client=llm, email_sender=email,
                                    database=db, trip_id=trip.id, store=store)
    await _run(orchestrator)


async def test_gate_drops_hallucinated_resource_keeps_real_one(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT, email_response=_email([HALLUCINATED, EMAIL.resources[0]]))
    email = FakeEmailSender()
    db = FakeDatabase()

    await _run_with_searches(monkeypatch, llm, email, db, trip, store)

    assert len(email.sent) == 1
    body = email.sent[0]["body"]
    assert "Senso-ji" in body
    assert "Castello Fantasma" not in body
    # one valid resource survived -> no retry needed
    assert len([p for p, m in llm.calls if m is EmailContent]) == 1


async def test_gate_dropped_resources_are_logged(monkeypatch, caplog):
    import logging

    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT, email_response=_email([HALLUCINATED, EMAIL.resources[0]]))
    email = FakeEmailSender()
    db = FakeDatabase()

    with caplog.at_level(logging.WARNING, logger="nostos.orchestrator"):
        await _run_with_searches(monkeypatch, llm, email, db, trip, store)

    assert any("invalid resources dropped" in r.getMessage() and "Castello Fantasma" in r.getMessage()
               for r in caplog.records)


async def test_gate_retry_second_attempt_succeeds_with_rejection_feedback(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT,
                  email_responses=[_email([HALLUCINATED]), _email([EMAIL.resources[0]])])
    email = FakeEmailSender()
    db = FakeDatabase()

    await _run_with_searches(monkeypatch, llm, email, db, trip, store)

    email_prompts = [p for p, m in llm.calls if m is EmailContent]
    assert len(email_prompts) == 2
    assert "rejected" in email_prompts[1] and "not in the list" in email_prompts[1]
    assert len(email.sent) == 1
    assert "Senso-ji" in email.sent[0]["body"]
    got = await store.get(trip.id)
    assert got.status == TripStatus.DONE


async def test_gate_both_attempts_hallucinated_fails_without_email(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT,
                  email_responses=[_email([HALLUCINATED]), _email([HALLUCINATED])])
    email = FakeEmailSender()
    db = FakeDatabase()

    await _run_with_searches(monkeypatch, llm, email, db, trip, store)

    assert email.sent == []
    assert db.saved == []
    got = await store.get(trip.id)
    assert got.status == TripStatus.ERROR
    assert "could not ground" in (got.result or "")
    assert len([p for p, m in llm.calls if m is EmailContent]) == 2


async def test_gate_empty_resources_on_both_attempts_fails_without_email(monkeypatch):
    store = make_store()
    trip = await store.create(make_trip())
    llm = FakeLLM(response=INTENT,
                  email_responses=[_email([]), _email([])])
    email = FakeEmailSender()
    db = FakeDatabase()

    await _run_with_searches(monkeypatch, llm, email, db, trip, store)

    assert email.sent == []
    assert db.saved == []
    got = await store.get(trip.id)
    assert got.status == TripStatus.ERROR
    assert "could not ground" in (got.result or "")
    assert len([p for p, m in llm.calls if m is EmailContent]) == 2
