"""Scoring: combina score Jev 0..1 con prezzo in codice. Mai inventare link."""

def pick_best_flight(flights: list[dict], scores: dict[str, float], budget_sensitive: bool) -> dict | None:
    if not flights:
        return None
    price_weight = 2.0 if budget_sensitive else 1.0
    prices = [f.get("price_eur") for f in flights if isinstance(f.get("price_eur"), (int, float))]
    pmax = max(prices) if prices else 1.0
    def cost(f: dict) -> float:
        s = float(scores.get(f.get("link", ""), 0.5))
        p = f.get("price_eur")
        norm = (float(p) / pmax) if isinstance(p, (int, float)) and pmax else 1.0
        return norm * price_weight - s
    return min(flights, key=cost)

def pick_top_pois(items: list[dict], scores: dict[str, float], limit: int = 3) -> list[dict]:
    ranked = sorted(items, key=lambda i: float(scores.get(i.get("link", ""), 0.5)), reverse=True)
    seen: set[str] = set()
    out: list[dict] = []
    for it in ranked:
        link = it.get("link") or ""
        if not link or link in seen:
            continue
        seen.add(link)
        out.append(it)
        if len(out) >= limit:
            break
    return out
