---
target: email cards
total_score: 16
max_score: 32
na_heuristics: 7,10
p0_count: 0
p1_count: 3
timestamp: 2026-09-26T17-48-58Z
slug: src-services-templates-email-html
---
# Critique — src/services/templates/email.html (Nostos trip email)

Method: dual-agent (A: design review · B: detector+evidence)
Score: 16/32 (Acceptable 50%; heuristics 7, 10 n/a as Read surface)

## Specificity: partially authored (6/10)
Nostos-owned: Greek masthead with gold hairlines, Fraunces italic lead, slow-travel kicker, founder signature, honest gap handling. Interchangeable: pale-blue cards with underlined titles + terracotta Apri, grey small-caps labels, gold-outline boxes. No place character, no route, no trip memory.

## Heuristics (0-4; 7,10 n/a)
1 Status 1 (no trip header/dates/party) · 2 Real world 2 (Ecco i punti di partenza, Apri, 4.3 stars, CEOs) · 3 Control 3 · 4 Consistency 2 (Vedi il volo vs Apri vs feedback; all titles underlined) · 5 Prevention 2 (prezzo non indicato x2 normalizes missing data) · 6 Recognition 1 (no Hai-chiesto context, no why-this-card) · 8 Aesthetic 3 (good pairing, low card/shell contrast, equal weights) · 9 Recovery 2 (collapses clean, no designed empty states).

## Cognitive load: 4/8 HIGH
Fails: chunking (undifferentiated scroll), grouping (cards blur into shell), minimal choices (8+ identical link targets), working memory (no trip summary).

## Emotional journey
Peak: opening italic line. Valley: understanding ends on missing flights + inventory heading + thin cards. Weak end: two gold boxes + button = being asked, not remembering Crete.

## Strengths
Editorial voice + Fraunces/Plex pairing; honest degradation that collapses (no broken headings/dupes); real email-client discipline (tables, inline, bulletproof button, dark overrides).

## Priority issues
P1 trip memory header missing (→ layout). P1 inventory framing Ecco i punti di partenza + DOVE STARE/COSA FARE (→ clarify). P1 duplicate link affordances title+Apri, hero title+Vedi il volo (→ harden). P2 missing-data copy verbatim incl. 4.3 stars mix (→ clarify). P2 triple-ask ending, generic travel box (→ distill).

## Detector (B)
Exit 2, 8 entries, single rule overused-font/Fraunces (stylistic preference; brand font — not a defect). Facts: 42 inline styles, 4+4 tables role=presentation, 15 dark classes, 520px breakpoint, 6 target=_blank in renderer, 0 img/alt, 0 h1-h6, font stacks with fallbacks. Hero arrival block + travel box lack d-* dark classes (will glare). Signature truncated by screenshot edge (capture artifact, not defect).

## Personas
Jordan: Greek masthead unexplained, Apri gives no destination hint, Festo assumed known, no next-step guidance. Casey: 14px inline taps, no anchors/day numbers, cards wash out in sunlight. Sam: duplicate same-URL links back-to-back, no headings/lists semantics, 11px italic note + pills contrast risk.
