# ADR-006: Knowledge base as a service guiding SerpAPI searches

## Status
Accepted

## Context
`src/knowledge.py` is empty and `src/knowledge/` holds only markdown travel
reports (camerun, creta, croazia, indonesia, islanda, sicilia) written by the
team. A `NOSTOS_QDRANT_URL` setting exists but is unused. Today the pipeline is
`intent extraction → SerpAPI (flights/POIs/stays) → email`: the searches are
driven exclusively by the extracted intent, so the accumulated travel knowledge
never influences the results.

The goal is a "level-1 tool call": right after intent extraction, the
orchestrator queries the knowledge base, extracts useful info about the
destination, and uses it to guide the SerpAPI searches.

## Decision
Treat knowledge as a **service** — `src/services/knowledge/` — invoked by
`TripOrchestrator` as the first step after intent extraction. The service:

1. matches the trip (destination, dates, interests, style) against the knowledge
   base,
2. returns structured, actionable info (e.g. off-season tips, authentic spots,
   places to avoid) that becomes additional input for the SerpAPI searches.

The knowledge base structure and retrieval strategy (markdown indexing vs
vector search on Qdrant) are **out of scope for this PR** and are defined in the
dedicated implementation PR. This decision only pins the architectural slot:
a service behind an interface, called by the orchestrator between intent
extraction and the searches.

## Consequences
- Positive: knowledge enriches the package and the markdown reports start to
  pay off; the rest of the pipeline is untouched; the service is isolated and
  testable with a fake.
- Negative: adds a dependency (Qdrant if vector search is chosen) and requires
  a defined KB structure before the service can be built.
- Deferred: KB schema/format, retrieval strategy (embeddings vs keyword), and
  whether the extracted knowledge also feeds email composition.

## Revisit When
- Starting the implementation PR: decide the KB structure and retrieval
  strategy, then relocate the current `src/knowledge/` reports under
  `src/services/knowledge/`.