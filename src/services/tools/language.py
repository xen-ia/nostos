"""Search language per destination.

SerpAPI `hl` was hardcoded to Italian everywhere, starving non-Italian
destinations (e.g. francophone Africa) of results. Italian at home, French
in francophone countries, English everywhere else. `gl` untouched.
"""

FRENCH_COUNTRIES = frozenset({
    "francia", "france", "belgio", "belgique", "belgium", "svizzera", "suisse",
    "camerun", "cameroun", "cameroon", "senegal", "sénégal", "marocco", "maroc",
    "morocco", "tunisia", "tunisie", "algeria", "algérie", "algerie", "madagascar",
    "mali", "niger", "ciad", "tchad", "chad", "gabon", "congo", "costa d'avorio",
    "côte d'ivoire", "burkina faso", "benin", "togo",
    "quebec", "québec", "haiti", "haïti", "lussemburgo", "luxembourg",
})

ITALY_NAMES = frozenset({"italia", "italy", "italie"})

LANG_NAMES = {"it": "Italian", "fr": "French", "en": "English"}


def search_language(countries: list[str | None]) -> str:
    """hl code for SerpAPI + query language hint for the LLM."""
    lowered = {(c or "").strip().lower() for c in countries if (c or "").strip()}
    if lowered & FRENCH_COUNTRIES:
        return "fr"
    if lowered & ITALY_NAMES:
        return "it"
    return "en"


def language_name(code: str) -> str:
    return LANG_NAMES.get(code, "English")
