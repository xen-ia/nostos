from src.core.decision_scoring import pick_best_flight, pick_top_pois

def test_pick_best_flight_prefers_cheap_useful():
    flights = [
        {"link": "u1", "price_eur": 300},
        {"link": "u2", "price_eur": 120},
    ]
    best = pick_best_flight(flights, {"u1": 0.9, "u2": 0.8}, False)
    assert best["link"] == "u2"

def test_pick_top_pois_orders_by_score():
    items = [{"link": "a", "name": "A"}, {"link": "b", "name": "B"}]
    assert [i["link"] for i in pick_top_pois(items, {"a": 0.4, "b": 0.95})] == ["b", "a"]
