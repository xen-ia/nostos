from src.core.models import TripPlan, DayStop
from src.core.trip_plan import sanitize_plan

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
    # only the first day keeps ref 0; label-only days carry no content and drop
    assert [d.day_label for d in clean.days] == ["G0"]

def test_sanitize_caps_distinct_days_to_7():
    plan = TripPlan(days=[DayStop(day_label=f"G{i}", poi_refs=[i]) for i in range(9)])
    clean = sanitize_plan(plan, flight_n=0, maps_n=9, places_n=0)
    assert [d.day_label for d in clean.days] == [f"G{i}" for i in range(7)]

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
