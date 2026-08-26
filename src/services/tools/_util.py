"""Shared helpers for SerpAPI-backed search tools."""


def dedupe_cap(items: list[dict], cap: int = 8) -> list[dict]:
    seen: set[tuple] = set()
    out: list[dict] = []
    for it in items:
        key = (it.get("name"), it.get("link"))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out[:cap]
