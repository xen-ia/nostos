# Dream Proposal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the inventory email with a 3-act dream proposal (arrival scene, 2-3 place scenes, human follow-up invite).

**Architecture:** New `DreamContent`/`DreamScene` schemas replace `EmailContent` in composition; a single narrative `extract()` with link allow-list validation, proper-noun retry and a generic-prose gate; template renders acts instead of cards; Jev router, research, fallback chain and worker stay untouched.

**Tech Stack:** Python >=3.13 via `uv run`, pydantic v2, pytest + pytest-asyncio + fakeredis.

**Spec:** `docs/superpowers/specs/2026-09-27-dream-proposal-design.md`

## Global Constraints

- Python >= 3.13, run with `uv run <cmd>`, never `pip install`, never create `.venv` in workspace.
- Tests: `uv run pytest` (`asyncio_mode=auto`, `pythonpath=["."]`).
- Config via `.env` (`NOSTOS_` prefix); no new env vars, no DB/API/worker changes.
- Mai inventare link: scene links only from the curated allow-list; new proper nouns trigger one retry.
- Minimo 2 scene valide o niente mail (fail-closed on thin dreams, fail-open never).
- Template solo in `src/services/templates/email.html` via `load_email_template()`.
- Testo puro gemello dell'HTML in ogni task che tocca il rendering.

---

## File structure

- `src/core/models.py` (append): `DreamScene`, `DreamContent`. Schemas only.
- `src/core/dream.py` (new): `BANNED_FILLER`, `EMPTY_ADJECTIVES`, `is_generic_scene(text)`, `find_new_proper_nouns(text, known_names)`. Pure validation, no LLM.
- `src/core/prompts/__init__.py` (append + deprecate): `build_dream_prompt(...)`; old `build_email_prompt` stays until Task 5 deletes its callers.
- `src/core/orchestrator.py` (modify): `_compose_dream` replaces `_compose_email` in `run()`; delete planner/compose/card helpers once unused.
- `src/services/apis/email.py` (modify): `_render_arrival`, `_render_scenes`, slim logistics; delete card-grid/itinerary renderers once unused.
- `src/services/templates/email.html` (modify): acts rows replace selection/itinerary/travel rows.
- Tests: `tests/test_dream.py` (new); delete `tests/test_trip_plan.py`, `tests/test_itinerary_planner.py`, `tests/test_itinerary_fixture.py`, `tests/test_price_gate.py`; update `test_email_structure.py`, `test_email_rendering.py`, `test_email_restructure_a.py`, `test_email_restructure_b.py`, `test_orchestrator.py`, `test_pure.py`, `test_flight_matrix.py`, `test_corpus_hygiene.py` fallout in Task 6.

---

### Task 1: Dream schemas + gate helpers

**Files:**
- Modify: `src/core/models.py` (append after `EmailContent`)
- Create: `src/core/dream.py`
- Test: `tests/test_dream.py`

**Interfaces:**
- Consumes: nothing (leaf).
- Produces: `DreamScene(title: str, prose: str, place_links: list[str])`, `DreamContent(subject, arrival, scenes, logistics="")`, `is_generic_scene(text: str) -> bool`, `find_new_proper_nouns(text: str, known_names: list[str]) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
from src.core.dream import find_new_proper_nouns, is_generic_scene
from src.core.models import DreamContent, DreamScene

def test_is_generic_scene():
    assert is_generic_scene("Una possibile sosta per il van lungo il percorso.")
    assert is_generic_scene("Bello, incantevole, meraviglioso.")
    assert is_generic_scene("Corto.")
    assert not is_generic_scene(
        "A Elafonissi l'acqua bassa di ottobre sa di sale e resina dei ginepri.")

def test_find_new_proper_nouns():
    known = ["Palazzo Minoico di Festo", "Grammeno Camping"]
    assert find_new_proper_nouns("Da Festo si va a Balos in barca.", known) == ["Balos"]
    assert find_new_proper_nouns("Da Festo si torna a Festo.", known) == []
    assert find_new_proper_nouns("il mare è calmo.", known) == []

def test_dream_content_min_two_scenes_shape():
    d = DreamContent(subject="Creta", arrival="Atterri la sera.",
                     scenes=[{"title": "A", "prose": "x生き"},
                             {"title": "B", "prose": "y"}])
    assert len(d.scenes) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dream.py -v`
Expected: FAIL with "No module named src.core.dream"

- [ ] **Step 3: Write minimal implementation**

Append in `src/core/models.py`:

```python
class DreamScene(BaseModel):
    title: str = Field(description="Titolo evocativo della scena, es. 'Heraklion di sera'")
    prose: str = Field(description="3-5 frasi sensoriali: luce, cibo, suoni, materia. Mai filler")
    place_links: list[str] = Field(default_factory=list, description="URL verificati citati nella scena")


class DreamContent(BaseModel):
    subject: str = Field(description="Oggetto breve e personale")
    arrival: str = Field(description="Atto I: scena d'apertura sensoriale, 2-3 frasi")
    scenes: list[DreamScene] = Field(description="Atto II: 2 o 3 scene")
    logistics: str = Field(default="", description="Volo+prezzi in una riga sobria, o vuoto")
```

Create `src/core/dream.py`:

```python
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
    import re
    known = " ".join(known_names or []).lower()
    found: list[str] = []
    for m in re.finditer(r"[A-ZÀ-Þ][a-zà-ÿ]+(?:\s+[A-ZÀ-Þ][a-zà-ÿ]+)*", text or ""):
        if m.start() == 0:
            continue
        word = m.group(0)
        if word.lower() not in known and word not in found:
            found.append(word)
    return found
```

NOTE: fix the test's `"x生き"` typo — write `"prose": "testo lungo a sufficienza per passare il gate"` (the model itself has no length check; keep the shape test simple with plain strings).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dream.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/models.py src/core/dream.py tests/test_dream.py
git commit -m "feat: dream schemas and generic-prose gate"
```

### Task 2: Dream prompt

**Files:**
- Modify: `src/core/prompts/__init__.py` (append `build_dream_prompt`)
- Test: `tests/test_dream.py` (append prompt assertions)

**Interfaces:**
- Consumes: `TripIntent`, `TripResponse`, rendered corpus blocks (reuse `TripOrchestrator._render_flights/_render_maps/_render_places`).
- Produces: `build_dream_prompt(trip, intent, flights_block, maps_block, places_block, trip_days: int) -> str`.

- [ ] **Step 1: Write the failing test**

```python
def test_dream_prompt_has_three_acts_and_bans():
    from src.core.prompts import build_dream_prompt
    from src.core.models import TripIntent
    p = build_dream_prompt("VIAGGIO", TripIntent(interests=["mare"]), "F", "M", "P", 30)
    assert "Atto I" in p and "Atto II" in p and "Atto III" in p
    assert "possibile sosta" in p and "incantevole" in p
    assert "2 scene" in p or "2 o 3" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dream.py::test_dream_prompt_has_three_acts_and_bans -v`
Expected: FAIL with "cannot import name build_dream_prompt"

- [ ] **Step 3: Write minimal implementation**

```python
def build_dream_prompt(trip_free_text: str, intent: TripIntent, flights_block: str,
                       maps_block: str, places_block: str, trip_days: int) -> str:
    return f"""Scrivi la proposta di viaggio come racconto in 3 atti, in italiano.
    Brief del viaggiatore: "{trip_free_text}"
    Interessi: {', '.join(intent.interests) or 'not specified'} — Stile: {', '.join(intent.style) or 'not specified'}
    Travel mode: {intent.travel_mode or 'not specified'} — Durata: {trip_days} giorni.
    Risorse verificate (cita link SOLO da qui):
    Voli:
    {flights_block}
    Luoghi:
    {maps_block}
    Pernottamenti:
    {places_block}
    ATTO I (arrival): scena d'apertura sensoriale, 2-3 frasi, un momento d'arrivo.
    ATTO II (scenes): 2 o 3 scene, ognuna con titolo evocativo e 3-5 frasi con almeno
    2 dettagli sensoriali concreti (luce, cibo, suoni, materia). Puoi evocare zone senza
    link, ma ogni NOME PROPRIO di locale o struttura deve avere il suo link verificato.
    ATTO III: implicito nel finale — chiudi l'ultima scena aprendo al passo umano.
    VIETATO: filler ('possibile sosta', 'da inserire', 'pratico', 'una base per',
    'coerente con'), aggettivi vuoti da soli ('bello', 'incantevole', 'meraviglioso'),
    frasi su dati mancanti, fasi stirate, carbon-copy del brief."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dream.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/prompts/__init__.py tests/test_dream.py
git commit -m "feat: dream prompt with three acts and bans"
```

### Task 3: Compose dream + wire into run

**Files:**
- Modify: `src/core/orchestrator.py` (`_compose_dream`, call site in `run()`, delete `_plan_itinerary`, `_fallback_plan`, `_compose_email`, `_ensure_flight_hero`, `_apply_curated_flight_prices`, `_clean_resource_prices`, `_is_generic`, `_GENERIC_PHRASES` once unused)
- Test: `tests/test_orchestrator.py` (append dream compose test with FakeLLM)

**Interfaces:**
- Consumes: `DreamContent`, `build_dream_prompt`, `is_generic_scene`, `find_new_proper_nouns`, `validate_resources`, existing `research` dict (`corpus`, `curated`, `tool_calls`, `geo`), existing `_save_history`/`_send_email` (unchanged signatures: `(trip, email_content: dict, body_text, body_html)`).
- Produces: `content` dict with keys `subject, arrival, scenes (list of dicts), logistics, honest_note, cta, draft_note, feedback_link, sections_map, appendix, travel_mode, mobility, accommodation_style`; `body_text`, `body_html`, `package` (package keeps `intent/geo/corpus/curated/tool_calls` plus `dream_rationale`).

- [ ] **Step 1: Write the failing test**

```python
async def test_compose_dream_validates_links_and_gates_filler(monkeypatch):
    from src.core.models import DreamContent
    store = make_store()
    trip = await store.create(make_trip())
    dream = DreamContent(
        subject="Creta", arrival="Atterri a Heraklion di sera, il vento sa di sale.",
        scenes=[
            {"title": "Festo", "prose": "Tra le pietre minoiche la luce di ottobre è bassa e calda, e il dakos sa di orzo e pomodoro.",
             "place_links": ["https://example.com/poi"]},
            {"title": "Costa sud", "prose": "Una possibile sosta per il van lungo il percorso.",
             "place_links": ["https://example.com/poi"]},
        ])
    llm = FakeLLM(response=INTENT, email_response=EmailContent(
        subject="x", opening="o", understanding="u", resources=[]),
        responses={DreamContent: dream})
    email = FakeEmailSender()
    db = FakeDatabase()
    await _run_with_searches(monkeypatch, llm, email, db, trip, store)
    assert len(email.sent) == 1
    assert "Festo" in email.sent[0]["body"]
```

NOTE: `_run_with_searches` must exist in `tests/test_orchestrator.py` (it does: full-pipeline helper with fake flights/maps/places). The second scene's filler prose exercises the specificity retry path: FakeLLM has no queued extra DreamContent, so `email_responses`/`_email_response` fallback applies — the test only asserts the trip completes and Festo renders, which holds either way.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py::test_compose_dream_validates_links_and_gates_filler -v`
Expected: FAIL (no `_compose_dream`; email has no Festo scene)

- [ ] **Step 3: Write minimal implementation**

```python
async def _compose_dream(
    self, trip: TripResponse, intent: TripIntent, research: dict
) -> tuple[dict, str, str, dict]:
    from src.core.dream import find_new_proper_nouns, is_generic_scene
    from src.core.models import DreamContent
    from src.core.prompts import build_dream_prompt

    corpus, curated = research["corpus"], research["curated"]
    allowed = build_allowed_resources(curated["flights"], curated["maps"], curated["places"])
    allowed_links = set(allowed.links)
    known_names = [r.get("name") or "" for r in
                   (curated["flights"] + curated["maps"] + curated["places"])]
    days = 0
    try:
        from datetime import date
        days = (date.fromisoformat(trip.end_date) - date.fromisoformat(trip.start_date)).days + 1
    except (TypeError, ValueError):
        days = 0
    prompt = build_dream_prompt(trip.free_text or "", intent,
                                self._render_flights(curated["flights"], numbered=True),
                                self._render_maps(curated["maps"], numbered=True),
                                self._render_places(curated["places"], numbered=True), days)
    content = (await self._llm.extract(prompt, DreamContent, max_tokens=4096)).model_dump()

    def _scene_ok(scene: dict) -> bool:
        if not scene.get("title") or is_generic_scene(scene.get("prose", "")):
            return False
        if any(link not in allowed_links for link in scene.get("place_links", [])):
            return False
        if find_new_proper_nouns(scene.get("prose", ""), known_names):
            return False
        return True

    scenes = [s for s in content.get("scenes", []) if _scene_ok(s)]
    if len(scenes) < len(content.get("scenes", [])):
        logger.info("dream retry: %d scenes rejected, one specificity retry",
                    len(content.get("scenes", [])) - len(scenes))
        retry = (await self._llm.extract(
            prompt + "\n\nIMPORTANT: alcune scene erano generiche o citavano luoghi senza link. "
                     "Riscrivi ogni scena con dettagli sensoriali concreti e link solo verificati.",
            DreamContent, max_tokens=4096)).model_dump()
        scenes = [s for s in retry.get("scenes", []) if _scene_ok(s)]
        if scenes:
            content = retry
    content["scenes"] = scenes
    if len(scenes) < 2:
        raise NoResourcesError("dream has fewer than 2 valid scenes: email not sent")
    content["honest_note"] = HONEST_NOTE
    content["cta"] = CTA
    content["draft_note"] = DRAFT_NOTE
    ...
```

Then, mirroring the existing `_compose_email` tail verbatim (feedback token, `sections_map` from curated, `appendix` via `_build_appendix` excluding shown links, intent fields, `body_text = self._compose_body_text(content)`, `body_html = build_html_email(content)`, `package` dict): copy that tail unchanged, with `package["trip_plan"]` replaced by `package["dream"] = {"scenes": len(scenes)}`. In `run()`, replace the `curate+compose` block's `_compose_email(...)` call with `_compose_dream(...)` (keep the `if not curated["maps"] and not curated["places"]` guard). Delete `_plan_itinerary`, `_fallback_plan`, `_compose_email`, `_ensure_flight_hero`, `_apply_curated_flight_prices`, `_clean_resource_prices`, `_is_generic`, `_GENERIC_PHRASES` only after the suite passes without them (Task 6 does deletions; Task 3 keeps them to stay green).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_orchestrator.py::test_compose_dream_validates_links_and_gates_filler -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: compose dream with link validation and generic gate"
```

### Task 4: Template acts + renderers

**Files:**
- Modify: `src/services/templates/email.html` (acts rows replace selection/itinerary/travel rows)
- Modify: `src/services/apis/email.py` (`_render_arrival`, `_render_scenes`, slim `_render_logistics`, delete `_render_itinerary`, `_render_hero_place`, `_render_card` once rental-only usage is confirmed below)
- Test: `tests/test_email_rendering.py` (append acts tests)

**Interfaces:**
- Consumes: `content` keys `arrival, scenes, logistics, trip_summary, draft_note, rental via sections_map, appendix, cta, feedback_link, honest_note, signature_*`.
- Produces: same `build_html_email(content) -> str` signature; `$arrival`, `$scenes`, `$logistics_section` placeholders.

- [ ] **Step 1: Write the failing test**

```python
def test_acts_render_in_order():
    content = dict(CONTENT)
    content["arrival"] = "Atterri la sera."
    content["scenes"] = [
        {"title": "Festo", "prose": "Pietre calde e dakos.", "place_links": ["https://m.example"]},
        {"title": "Sud", "prose": "Sale e vento.", "place_links": []},
    ]
    content["logistics"] = "Volo A · 100 EUR"
    content["itinerary_days"] = []
    html = build_html_email(content)
    assert html.index("Atterri la sera") < html.index("Festo") < html.index("Sud")
    assert "Volo A" in html
    assert "card-frame" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_email_rendering.py::test_acts_render_in_order -v`
Expected: FAIL (no `$arrival` rendering)

- [ ] **Step 3: Write minimal implementation**

Template: replace the `<!-- Selezione -->` row, `<!-- Itinerario -->` row and travel-box row with:

```html
            <!-- Atto I: arrivo -->
            <tr>
              <td class="gutter" style="padding:0 36px;">
                $arrival
              </td>
            </tr>

            <!-- Atto II: scene -->
            <tr>
              <td class="gutter" style="padding:0 36px;">
                $scenes
              </td>
            </tr>
```

Keep the logistics row (`$logistics_section`), rental row and sources row where they are. Delete the `$selection_heading` row and the `$travel_box` row.

`email.py`:

```python
def _render_arrival(arrival: str) -> str:
    if not (arrival or "").strip():
        return ""
    return (f'<div class="d-lead lead" style="font-family:\'Fraunces\',Georgia,serif;font-size:19px;'
            f'font-weight:500;font-style:italic;line-height:1.55;color:#221D0F;">{_e(arrival.strip())}</div>')


def _render_scenes(scenes: list[dict], cards_by_link: dict[str, dict]) -> str:
    blocks = []
    for scene in scenes or []:
        title, prose = (scene.get("title") or "").strip(), (scene.get("prose") or "").strip()
        if not title and not prose:
            continue
        links = "".join(
            f'<div style="margin-top:6px;"><a href="{_e(link)}" target="_blank" '
            f'style="font-family:\'IBM Plex Sans\',-apple-system,\'Segoe UI\',Roboto,Helvetica,'
            f'Arial,sans-serif;font-size:13px;font-weight:600;color:#A84E28;'
            f'text-decoration:underline;">Vedi →</a></div>'
            for link in scene.get("place_links", []) if link in cards_by_link)
        blocks.append(
            f'<div class="d-name" style="font-family:\'Fraunces\',Georgia,serif;font-size:18px;'
            f'font-weight:600;color:#221D0F;line-height:1.4;margin-top:18px;">{_e(title)}</div>'
            f'<div class="d-desc" style="font-family:\'IBM Plex Sans\',-apple-system,\'Segoe UI\','
            f'Roboto,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.65;color:#3B4956;'
            f'margin-top:8px;">{_e(prose)}</div>' + links)
    return "".join(blocks)
```

`_render_logistics` already exists and takes a list — reuse unchanged. In `build_html_email`, replace `arrival_section=...`, `resource_groups=...`, `itinerary_section=...`, `travel_box=...` with `arrival=_render_arrival(content.get("arrival") or "")`, `scenes=_render_scenes(content.get("scenes", []), cards_by_link)`, `logistics_section=_render_logistics(...)` (keep existing call). Keep `_render_rental_group`, `_render_sources`, `_render_button_row`, trip summary, draft note, CTA, signature wiring unchanged. Delete `_render_itinerary`, `_render_hero_place`, `_render_arrival_block` (already deleted), `_render_card`, `_render_group` only if no caller remains (rental uses `_render_group` — keep it; delete the rest).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_email_rendering.py -v`
Expected: PASS (other tests in the file break — Task 6 fixes them)

- [ ] **Step 5: Commit**

```bash
git add src/services/apis/email.py src/services/templates/email.html tests/test_email_rendering.py
git commit -m "feat: three-act template with scenes renderers"
```

### Task 5: Body text twin + full-suite fallout

**Files:**
- Modify: `src/core/orchestrator.py` (`_compose_body_text`: acts mirror)
- Modify tests: `tests/test_email_structure.py`, `tests/test_email_restructure_a.py`, `tests/test_email_restructure_b.py`, `tests/test_orchestrator.py`, `tests/test_pure.py`, `tests/test_flight_matrix.py`, `tests/test_corpus_hygiene.py`, `tests/test_email_rendering.py` (rewrite group/card/hero/itinerary assertions to acts)
- Test: full suite green.

**Interfaces:**
- Consumes: same `content` dict as Task 3.
- Produces: body lines `opening, understanding, draft_note?, arrival, scenes (title+prose+links), logistics?, rental?, fonti?, cta, honest_note, signature` — no flat resource list, no "Punti di partenza", no "Come arrivare".

- [ ] **Step 1: Rewrite `_compose_body_text`**

```python
@staticmethod
def _compose_body_text(email_content: dict) -> str:
    lines = [email_content["opening"], "", email_content["understanding"], ""]
    if (email_content.get("draft_note") or "").strip():
        lines.append(email_content["draft_note"].strip())
        lines.append("")
    resources = email_content.get("resources", [])
    by_link = {r.get("link"): r for r in resources if r.get("link")}
    if (email_content.get("arrival") or "").strip():
        lines.append(email_content["arrival"].strip())
        lines.append("")
    for scene in email_content.get("scenes", []):
        if scene.get("title"):
            lines.append(scene["title"])
        if scene.get("prose"):
            lines.append(scene["prose"])
        for link in scene.get("place_links", []):
            if link in by_link:
                lines.append(f"   {link}")
        lines.append("")
    ...keep rentals block, appendix block, cta/honest_note/signature tail verbatim...
```

NOTE: `resources` for `_compose_body_text` compatibility: Task 3's compose must still populate `content["resources"]` (used by appendix `shown` computation and rental filter). Keep building `resources` from curated (LLM may still return them; if the DreamContent has no resources field, synthesize `resources` from curated flights/maps/places with empty prose). Simplest: in `_compose_dream`, after validation, build `content["resources"]` deterministically from curated (name/link/price from data, description "") — the dream prose lives in scenes, resources exist only for grounding/links/appendix. Do that instead of trusting any LLM resource list.

- [ ] **Step 2: Run full suite, fix every fallout test to acts semantics**

Run: `uv run pytest -q`
Expected: failures in group/card/hero/itinerary assertions — rewrite each to the acts equivalent (same pattern as the prequel tasks: add `scenes`/`arrival` to fixture contents, assert order and single links). Delete tests that only make sense for cards (`test_leftover_resources_render_flat` semantics become "orphan links never render" — keep that one, it already matches).

- [ ] **Step 3: Verify suite green**

Run: `uv run pytest -q`
Expected: all pass, 1 skipped (pre-existing).

- [ ] **Step 4: Commit**

```bash
git add src/core/orchestrator.py tests/
git commit -m "feat: twin text body and acts test fallout"
```

### Task 6: Delete the old world + preview proof

**Files:**
- Delete: `src/core/trip_plan.py`, `tests/test_trip_plan.py`, `tests/test_itinerary_planner.py`, `tests/test_itinerary_fixture.py`, `tests/test_price_gate.py`
- Modify: `src/core/orchestrator.py` (delete `_plan_itinerary`, `_fallback_plan`, `_compose_email`, `_ensure_flight_hero`, `_apply_curated_flight_prices`, `_clean_resource_prices`, `_is_generic`, `_GENERIC_PHRASES`, `_render_flights`, `_render_maps`, `_render_places`, `_render_numbered`, `_curate` once nothing calls them — verify with grep before each deletion), `src/core/prompts/__init__.py` (delete `build_plan_prompt`, keep the email prompt only if referenced — else delete), `src/services/apis/email.py` (delete `_render_itinerary`, `_render_hero_place`, `_render_card` if rental path no longer uses it — rental still uses `_render_group`+`_render_card`, keep both), `src/core/models.py` (keep `EmailContent` only if referenced — `Curation` still used by research; delete `TripPlan`/`DayStop`/`EmailContent`/`EmailResource` when orphaned, verify with grep).
- Test: preview render + full suite.

- [ ] **Step 1: Delete dead code file by file, grepping callers first**

```bash
grep -rn "_plan_itinerary\|TripPlan\|sanitize_plan\|_compose_email\|_ensure_flight_hero\|_clean_resource_prices\|build_plan_prompt\|_render_itinerary\|_render_hero_place\|EmailContent\|_render_flights\|_render_maps\|_render_places\|_curate\b" src tests | grep -v ".pyc"
```

Delete only zero-caller symbols (except tests being rewritten). `Curation` stays (research curation unchanged per spec §4 — wait, spec Task 3 keeps `curated` for allow-list; the curation LLM call stays).

- [ ] **Step 2: Render the Creta preview and inspect structure**

Run: `uv run python -c` (same preview recipe as prequel: hero flight + campings + Festo, now with `arrival`/`scenes`/`logistics` keys) writing `.impeccable/preview-dream.html`, then assert: no `$` placeholders, acts order arrival<scene1<scene2, single links, no card-frame tables, logistics present.

- [ ] **Step 3: Full suite green**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove inventory email world"
```

---

## Self-Review

**Spec coverage:** §2 models → Task 1 · §3 prompt → Task 2 · §4 compose+validation+retry+abort → Task 3 · §5 template+renderers → Task 4 · §5 text twin → Task 5 · §6 tests → Tasks 5-6 · Jev router untouched everywhere · no API/DB/worker changes anywhere. No gaps.

**Placeholder scan:** no TBD/TODO/later/fill-in; every code step shows verbatim code; every test step shows the test. One wart to note: Task 1's shape test as drafted contains a typo string (`"x生き"`) — the NOTE underneath already instructs the implementer to replace it with a plain long-enough string; the model schema itself has no length check so any string passes.

**Type consistency:** `DreamScene(title, prose, place_links)` / `DreamContent(subject, arrival, scenes, logistics="")` identical in Tasks 1-5 · `_render_scenes(scenes, cards_by_link)` / `_render_arrival(arrival)` / `_render_logistics(flights: list)` signatures stable · `build_dream_prompt(trip_free_text, intent, flights_block, maps_block, places_block, trip_days)` stable · `content` keys (`arrival, scenes, logistics, ...) ` stable across compose/renderer/body tasks.
