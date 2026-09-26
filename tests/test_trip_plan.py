from src.core.models import TripPlan, DayStop
from src.core.trip_plan import sanitize_plan, transition_names_a_stop

def test_transition_names_a_stop():
    names = ["Camping Paleochora", "Palazzo Minoico di Festo"]
    assert transition_names_a_stop("Spostamento verso Paleochora e pernottamenti a bordo.", names)
    assert transition_names_a_stop("Visita a Festo al mattino.", names)
    assert not transition_names_a_stop("Tappe corte, senza fretta.", names)
    assert not transition_names_a_stop("", names)

def test_plan_prompt_requires_named_transitions():
    from src.core.prompts import build_plan_prompt
    from src.core.models import TripIntent
    from src.core.schemas import TripResponse, TripStatus
    trip = TripResponse(id="t", status=TripStatus.PENDING, received_at="2026-09-20T00:00:00+00:00",
        email="a@b.it", destination="Creta", free_text="van")
    prompt = build_plan_prompt(trip, TripIntent(), "n", "n", "n", 30)
    assert "DEVE nominare almeno una delle tappe" in prompt

def test_sanitize_drops_bad_refs_and_url_transition():
    plan = TripPlan(days=[
        DayStop(day_label="Giorni 1-7 · X", poi_refs=[0, 9], stay_refs=[0],
                transition="dettagli su https://esempio.it/x"),
    ])
    clean = sanitize_plan(plan, flight_n=1, maps_n=3, places_n=2)
    assert clean.days[0].poi_refs == [0]
    assert clean.days[0].stay_refs == [0]
    assert clean.days[0].transition == ""

def test_sanitize_caps_to_7_and_drops_empty():
    plan = TripPlan(days=[
        DayStop(day_label=f"G{i}", poi_refs=[0]) for i in range(9)
    ] + [DayStop(day_label="vuota")])
    clean = sanitize_plan(plan, flight_n=0, maps_n=3, places_n=0)
    # only the first day keeps ref 0; label-only days carry no content and drop;
    # uncovered refs 1-2 land in the final coverage phase
    assert [d.day_label for d in clean.days] == ["G0", "Altre tappe lungo il percorso"]
    assert clean.days[1].poi_refs == [1, 2]

def test_sanitize_caps_distinct_days_to_7():
    plan = TripPlan(days=[DayStop(day_label=f"G{i}", poi_refs=[i]) for i in range(9)])
    clean = sanitize_plan(plan, flight_n=0, maps_n=9, places_n=0)
    assert [d.day_label for d in clean.days] == [f"G{i}" for i in range(7)]

def test_sanitize_appends_uncovered_refs_to_final_phase():
    plan = TripPlan(days=[DayStop(day_label="G1", poi_refs=[0])])
    clean = sanitize_plan(plan, flight_n=1, maps_n=3, places_n=2)
    labels = [d.day_label for d in clean.days]
    assert labels[0] == "G1"
    assert labels[-1] == "Altre tappe lungo il percorso"
    tail = clean.days[-1]
    assert tail.flight_refs == [0]
    assert sorted(tail.poi_refs) == [1, 2]
    assert tail.stay_refs == [0, 1]

def test_sanitize_no_extra_phase_when_fully_covered():
    plan = TripPlan(days=[DayStop(day_label="G1", poi_refs=[0], stay_refs=[0])])
    clean = sanitize_plan(plan, flight_n=0, maps_n=1, places_n=1)
    assert [d.day_label for d in clean.days] == ["G1"]

def test_sanitize_dedupes_stop_across_days():
    plan = TripPlan(days=[
        DayStop(day_label="G1", poi_refs=[0, 1]),
        DayStop(day_label="G2", poi_refs=[1, 2], stay_refs=[0]),
        DayStop(day_label="G3", stay_refs=[0], transition="pernottamenti a bordo."),
    ])
    clean = sanitize_plan(plan, flight_n=0, maps_n=3, places_n=1)
    assert clean.days[0].poi_refs == [0, 1]
    assert clean.days[1].poi_refs == [2]
    assert clean.days[1].stay_refs == [0]
    # G3 loses its only stop to the dupe rule but keeps the transition
    assert clean.days[2].stay_refs == []
    assert clean.days[2].transition == "pernottamenti a bordo."

def test_sanitize_strips_flight_mentions_without_curated_flights():
    plan = TripPlan(days=[
        DayStop(day_label="G1", poi_refs=[0],
                transition="Arrivo e pernottamenti a bordo. Non sono disponibili voli curati."),
    ])
    clean = sanitize_plan(plan, flight_n=0, maps_n=1, places_n=0)
    assert "volo" not in clean.days[0].transition.lower()
    assert "Arrivo" in clean.days[0].transition

def test_sanitize_keeps_flight_mentions_with_curated_flights():
    plan = TripPlan(days=[
        DayStop(day_label="G1", flight_refs=[0],
                transition="Arrivo con il volo del mattino."),
    ])
    clean = sanitize_plan(plan, flight_n=1, maps_n=0, places_n=0)
    assert "volo" in clean.days[0].transition.lower()
