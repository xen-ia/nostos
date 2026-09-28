"""Dream validation: filler ban + proper-noun grounding check. Pure code."""

BANNED_FILLER = ("possibile sosta", "da inserire", "pratico per", "pratica per",
                 "una base per", "coerente con")
EMPTY_ADJECTIVES = ("bello", "incantevole", "meraviglioso", "stupendo", "magico")


def is_generic_scene(text: str | None) -> bool:
    t = (text or "").strip()
    if not t or len(t) < 40:
        return True
    lowered = t.lower()
    if any(p in lowered for p in BANNED_FILLER):
        return True
    words = [w.strip(".,;:!?") for w in lowered.split()]
    meaningful = [w for w in words if w not in EMPTY_ADJECTIVES]
    return len(meaningful) < 12


def find_new_proper_nouns(text: str, known_names: list[str]) -> list[str]:
    """Capitalized words never seen in the corpus — sentence-initial tokens
    excluded (ordinary words like Poi/Il/Dal start sentences too)."""
    import re
    known = " ".join(known_names or []).lower()
    found: list[str] = []
    sentences = re.split(r"(?<=[.!?])\s+", text or "")
    for sent in sentences:
        matches = re.findall(r"[A-ZÀ-Þ][a-zà-ÿ]+(?:\s+[A-ZÀ-Þ][a-zà-ÿ]+)*", sent)
        for word in matches[1:]:
            if word.lower() not in known and word not in found:
                found.append(word)
    return found
