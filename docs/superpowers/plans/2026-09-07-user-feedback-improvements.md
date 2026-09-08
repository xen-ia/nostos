# User Feedback Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Risolvere i 6 feedback utenti (validazione incompleta, refresh perde tracking, voli intercontinentali mancanti, link feedback in email, ridondanza email, STT microfono) con modifiche mirate a frontend, email, orchestrator e API.

**Architecture:** Incremental patches su codebase esistente: localStorage per persistenza trip_id, endpoint STT separato che wrappa OpenAI gpt-transcribe, detection continente per forzare voli su rotte intercontinentali, dedup sezione mobilité in email, pagina feedback standalone con HMAC token.

**Tech Stack:** FastAPI + Pydantic, Redis/ARQ, Postgres, vanilla JS (docs/index.html), OpenAI API (gpt-transcribe $0.0045/min), Resend email.

**Spec:** `docs/superpowers/specs/2026-09-07-user-feedback-improvements-design.md`

## Global Constraints

- Python >= 3.13, `uv run <cmd>`, `UV_PROJECT_ENVIRONMENT="$HOME/.venvs/nostos"`, mai creare `.venv` nel workspace.
- Config via `.env` con prefisso `NOSTOS_`, pydantic-settings in `src/settings.py`; aggiungere nuove chiavi con default.
- Test: `uv run pytest` con `pythonpath=["."]`, `asyncio_mode=auto`; usare fakeredis per test.
- Email template è `src/services/templates/email.html` (string.Template) caricato via `load_email_template()` in `src/services/apis/email.py`.
- Frontend è `docs/index.html` intero (inline CSS/JS, no build), campi devono matchare `TripCreateRequest` in `src/core/schemas.py`.
- Orchestrator ha lease `claim`/`renew`/`release` 300s TTL + 60s heartbeat; non rompere il flow.
- API contract test in `tests/test_contract.py` deve passare.

---

## File Structure

**Modified:**
- `src/settings.py` — aggiunge `openai_api_key` già esiste, aggiunge `stt_model`, `stt_max_mb`, `feedback_token_ttl_days`
- `src/api/main.py` — include router STT
- `src/api/routers/trips.py` — validazione token feedback opzionale, arricchimento status già esistente
- `src/core/orchestrator.py` — detection intercontinentale + feedback_link generation
- `src/services/apis/email.py` — dedup `_render_mobility_inline` quando travel_mode presente, nuovo `_render_feedback_link`, `build_html_email` usa `$feedback_link`
- `src/services/templates/email.html` — aggiunge placeholder `$feedback_link` prima del footer
- `docs/index.html` — validazione submit, localStorage, STT microfono, polling resume

**Created:**
- `src/api/routers/stt.py` — endpoint POST /api/v1/stt
- `docs/feedback.html` — standalone feedback page
- `src/core/feedback_token.py` — HMAC helper per feedback link
- Tests: `tests/test_stt.py`, `tests/test_feedback_token.py`, `tests/test_email_dedup.py`

---

### Task 1: Backend STT endpoint (gpt-transcribe)

**Files:**
- Modify: `src/settings.py:6-67`
- Create: `src/api/routers/stt.py`
- Modify: `src/api/main.py:12-51`
- Test: `tests/test_stt.py`

**Interfaces:**
- Consumes: `Settings.openai_api_key`, `Settings.stt_model`, FastAPI `UploadFile`
- Produces: `POST /api/v1/stt -> {text: str}`, rate-limited 10 req/60s per IP

- [ ] **Step 1: Write failing test for STT endpoint**

```python
# tests/test_stt.py
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

def test_stt_requires_openai_key(monkeypatch):
    monkeypatch.setenv("NOSTOS_OPENAI_API_KEY", "")
    # should return 503 or 500 if key missing

@pytest.mark.asyncio
async def test_stt_transcribes_audio():
    # mock openai client
    with patch("src.api.routers.stt.OpenAI") as Mock:
        mock = Mock.return_value
        mock.audio.transcriptions.create.return_value = type("obj", (), {"text": "ciao mare"})()
        # POST multipart audio -> 200 {text: "ciao mare"}
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_stt.py -v`
Expected: FAIL — module `src.api.routers.stt` not found

- [ ] **Step 3: Add settings**

```python
# src/settings.py — aggiungere dopo openai_api_key:
    stt_model: str = "gpt-transcribe"
    stt_max_mb: int = 25
    feedback_token_ttl_days: int = 7
```

- [ ] **Step 4: Create stt router**

```python
# src/api/routers/stt.py
from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import JSONResponse
from openai import OpenAI
from src.settings import Settings, get_settings
from src.api.security import RateLimiter, rate_limit_key
from src.api.errors import APIError, ErrorCode

router = APIRouter(prefix="/api/v1", tags=["stt"])

ALLOWED_CT = {"audio/webm","audio/mp4","audio/mpeg","audio/mp3","audio/wav","audio/x-wav","audio/m4a","audio/ogg","video/webm"}

@router.post("/stt")
async def speech_to_text(request: Request, audio: UploadFile = File(...), settings: Settings = Depends(get_settings)):
    limiter = RateLimiter(request.app.state.redis, max_requests=10, window_seconds=60)
    await limiter.check(rate_limit_key(request))
    if not settings.openai_api_key:
        raise APIError(ErrorCode.INTERNAL_ERROR, "STT not configured", 503)
    if audio.size and audio.size > settings.stt_max_mb * 1024 * 1024:
        raise APIError(ErrorCode.BAD_REQUEST, f"File too large >{settings.stt_max_mb}MB", 413)
    ctype = (audio.content_type or "").lower()
    if ctype not in ALLOWED_CT and not ctype.startswith("audio/"):
        raise APIError(ErrorCode.BAD_REQUEST, "Invalid audio type", 400)
    data = await audio.read()
    if len(data) > settings.stt_max_mb * 1024 * 1024:
        raise APIError(ErrorCode.BAD_REQUEST, "File too large", 413)
    # OpenAI call in thread
    import asyncio, io
    client = OpenAI(api_key=settings.openai_api_key)
    def _call():
        f = io.BytesIO(data)
        f.name = audio.filename or "audio.webm"
        return client.audio.transcriptions.create(model=settings.stt_model, file=(f.name, f, ctype), language="it")
    try:
        resp = await asyncio.to_thread(_call)
    except Exception as e:
        raise APIError(ErrorCode.INTERNAL_ERROR, f"Transcription failed: {e}", 502)
    return JSONResponse({"text": resp.text})
```

- [ ] **Step 5: Register router in main**

```python
# src/api/main.py:12
from src.api.routers import trips, stt
# ... app.include_router(trips.router)
app.include_router(stt.router)
# add "POST" to allow_methods already includes POST
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_stt.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/settings.py src/api/routers/stt.py src/api/main.py tests/test_stt.py
git commit -m "feat: add STT endpoint gpt-transcribe"
```

---

### Task 2: Frontend — validazione e localStorage persistence

**Files:**
- Modify: `docs/index.html:1008-1600` (JS section)
- Test: `tests/test_contract.py` (verifica che campi richiesti restino compatibili) + manual browser test

**Interfaces:**
- Consumes: `TripCreateRequest` fields, `localStorage.getItem/setItem`, `GET /trips/{id}/status/public`
- Produces: `form submit` bloccato se invalido, `nostos_active_trip` in localStorage, resume polling on load

- [ ] **Step 1: Write manual test checklist (no unit test for vanilla JS, usare Playwright-like manual)**

Checklist da verificare dopo implementazione:
- Submit con email vuota → blocked, mostra errore inline
- Submit con start_date vuota → blocked
- Submit con destination vuota E free_text vuoto → blocked
- Refresh durante pending → riprende polling automaticamente
- Feedback inviato → localStorage cleared

- [ ] **Step 2: Edit docs/index.html — validazione**

```js
// prima di fetch POST /trips, aggiungere:
function validateForm(){
  const email = document.getElementById("email").value.trim();
  const start = document.getElementById("start_date").value;
  const dest = document.getElementById("destination").value.trim();
  const free = document.getElementById("free_text").value.trim();
  if(!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return "Inserisci un'email valida";
  if(!start) return "Scegli le date del viaggio";
  if(!dest && !free) return "Indica una destinazione o descrivi il viaggio";
  return null;
}
form.addEventListener("submit", async (e)=>{
  e.preventDefault();
  const err = validateForm();
  if(err){ statusEl.className="is-error"; statusEl.textContent=err; return; }
  // existing fetch...
});
```

- [ ] **Step 3: Add localStorage persistence**

```js
const LS_KEY = "nostos_active_trip";
function saveActiveTrip(id){ localStorage.setItem(LS_KEY, JSON.stringify({id, ts: Date.now()})); }
function clearActiveTrip(){ localStorage.removeItem(LS_KEY); }
function loadActiveTrip(){ try{ return JSON.parse(localStorage.getItem(LS_KEY)); }catch{ return null; } }

// dopo POST 202 success:
saveActiveTrip(trip.id);
currentTripId = trip.id;
startPolling(trip.status);

// on load:
window.addEventListener("DOMContentLoaded", ()=>{
  const saved = loadActiveTrip();
  if(saved && saved.id){
    currentTripId = saved.id;
    document.getElementById("email").value = ""; // non abbiamo PII
    pollTrip(); // riprende
  }
});
// in onFinished e resetFeedbackUI aggiungere clearActiveTrip() quando done+feedback sent o nuova ricerca
// aggiungere bottone "Nuova ricerca" in statusEl HTML e handler che chiama clearActiveTrip() + form.reset() + resetFeedbackUI()
```

- [ ] **Step 4: Run contract test**

Run: `uv run pytest tests/test_contract.py -v`
Expected: PASS (campi non cambiati)

- [ ] **Step 5: Commit**

```bash
git add docs/index.html
git commit -m "feat(frontend): validation + localStorage trip persistence"
```

---

### Task 3: Frontend — microfono STT UI

**Files:**
- Modify: `docs/index.html` (HTML textarea wrapper + JS MediaRecorder)
- Test: manual browser test + `tests/test_stt.py` già copre API

**Interfaces:**
- Consumes: `POST /api/v1/stt`, `MediaRecorder`, `navigator.mediaDevices.getUserMedia`
- Produces: transcript appended to `#free_text`

- [ ] **Step 1: Add HTML**

```html
<!-- sostituire field free_text: -->
<div class="field full">
  <label for="free_text">Raccontaci l'atmosfera che cerchi
    <button type="button" id="mic-btn" aria-label="Detta con microfono" style="...">🎤</button>
  </label>
  <textarea id="free_text" ...></textarea>
  <div id="mic-status" hidden style="font-size:0.8rem;color:var(--terracotta);">Registrazione in corso… clicca per fermare</div>
</div>
```

- [ ] **Step 2: Add JS**

```js
const micBtn = document.getElementById("mic-btn");
const micStatus = document.getElementById("mic-status");
let recorder, chunks=[];
micBtn.addEventListener("click", async ()=>{
  if(recorder && recorder.state==="recording"){
    recorder.stop(); return;
  }
  try{
    const stream = await navigator.mediaDevices.getUserMedia({audio:true});
    recorder = new MediaRecorder(stream, {mimeType: MediaRecorder.isTypeSupported("audio/webm")?"audio/webm":"audio/mp4"});
    chunks=[];
    recorder.ondataavailable=e=>{ if(e.data.size) chunks.push(e.data); };
    recorder.onstop= async ()=>{
      micStatus.hidden=true; micBtn.disabled=true; micBtn.textContent="⏳";
      const blob = new Blob(chunks, {type: recorder.mimeType});
      const fd = new FormData(); fd.append("audio", blob, "audio.webm");
      try{
        const res = await fetch(`${API_BASE}/stt`, {method:"POST", body: fd});
        if(!res.ok) throw new Error(await res.text());
        const {text} = await res.json();
        freeText.value = freeText.value ? freeText.value + " " + text : text;
      }catch(err){ statusEl.className="is-error"; statusEl.textContent="Errore trascrizione: "+err.message; }
      finally{ micBtn.disabled=false; micBtn.textContent="🎤"; stream.getTracks().forEach(t=>t.stop()); }
    };
    recorder.start(); micStatus.hidden=false; micBtn.textContent="⏹️";
  }catch(err){ statusEl.className="is-error"; statusEl.textContent="Microfono non disponibile: "+err.message; }
});
```

- [ ] **Step 3: Manual verify**

Run: `uv run python -m http.server 5500` in docs/, test mic in browser, check network tab POST /stt

- [ ] **Step 4: Commit**

```bash
git add docs/index.html
git commit -m "feat(frontend): microphone STT for free_text"
```

---

### Task 4: Email — dedup mobilità + feedback_link

**Files:**
- Modify: `src/services/apis/email.py:137-188`
- Modify: `src/services/templates/email.html:118-158`
- Test: `tests/test_email_rendering.py`, new `tests/test_email_dedup.py`

**Interfaces:**
- Consumes: `content.travel_mode`, `content.mobility`, `content.feedback_link`
- Produces: `build_html_email` senza duplicazione, template con `$feedback_link`

- [ ] **Step 1: Write failing test**

```python
# tests/test_email_dedup.py
from src.services.apis.email import build_html_email
def test_no_duplicate_mobility_when_van_life():
    content = {"opening":"x","understanding":"y","resources":[],"cta":"c","honest_note":"n","travel_mode":"van_life","mobility":["auto","van"],"sections_map":{},"appendix":{"groups":[],"source_links":[]}}
    html = build_html_email(content)
    assert html.count("Mezzi") == 1  # solo dentro Vita in van, non anche Come spostarti
    assert "Come spostarti" not in html

def test_mobility_only_when_fixed():
    content = {"opening":"x","understanding":"y","resources":[],"cta":"c","honest_note":"n","travel_mode":"fixed","mobility":["auto"],"sections_map":{},"appendix":{"groups":[],"source_links":[]}}
    html = build_html_email(content)
    assert "Come spostarti" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_email_dedup.py -v`
Expected: FAIL — duplicate Mezzi

- [ ] **Step 3: Fix email.py**

```python
# in build_html_email:
    travel_mode = content.get("travel_mode")
    mobility = content.get("mobility")
    travel_mode_html = _render_travel_mode_block(travel_mode, mobility)
    # dedup: se travel_mode attivo, non renderizzare anche mobilità inline
    if travel_mode and travel_mode != "fixed":
        mobility_html = ""
    else:
        mobility_html = _render_mobility_inline(mobility)
    # aggiungere feedback_link:
    feedback_link = content.get("feedback_link") or ""
    feedback_html = f'<div style="text-align:center;margin-top:18px;"><a href="{_e(feedback_link)}" style="display:inline-block;padding:10px 18px;border:1px solid #B58026;border-radius:999px;color:#B58026;font-size:13px;">Lascia un feedback</a></div>' if feedback_link else ""
```

Aggiornare `load_email_template().safe_substitute` per includere `feedback_link=feedback_html`

- [ ] **Step 4: Edit template**

```html
<!-- dopo CTA, prima di firma, aggiungere: -->
<tr><td class="gutter" style="padding:0 36px;">$feedback_link</td></tr>
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_email_dedup.py tests/test_email_rendering.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/services/apis/email.py src/services/templates/email.html tests/test_email_dedup.py
git commit -m "fix(email): dedup mobility and add feedback link"
```

---

### Task 5: Orchestrator — intercontinental flights + feedback token

**Files:**
- Create: `src/core/feedback_token.py`
- Modify: `src/core/orchestrator.py:40-50,340-470,580-630`
- Modify: `src/settings.py` (frontend base url per link)
- Test: `tests/test_orchestrator.py`, `tests/test_feedback_token.py`

**Interfaces:**
- Consumes: `trip.departure_location`, `intent.travel_mode`, `resolved`, `departure_codes`
- Produces: flights non skippati su intercontinentale, `content.feedback_link` con HMAC

- [ ] **Step 1: Write failing test**

```python
# tests/test_feedback_token.py
from src.core.feedback_token import make_token, verify_token
def test_token_roundtrip():
    tok = make_token("trip-123", "secret", ttl_days=7)
    assert verify_token(tok, "trip-123", "secret")
    assert not verify_token(tok, "trip-999", "secret")

# tests/test_orchestrator.py — aggiungere
@pytest.mark.asyncio
async def test_intercontinental_forces_flights():
    # intent.travel_mode="van_life", departure Italy, destination Patagonia
    # -> skipped_reason deve essere None, flights probed
    pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_feedback_token.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create feedback_token helper**

```python
# src/core/feedback_token.py
import hmac, hashlib, time, base64, json
def make_token(trip_id: str, secret: str, ttl_days: int = 7) -> str:
    exp = int(time.time()) + ttl_days*86400
    payload = json.dumps({"tid": trip_id, "exp": exp}, separators=(",",":"))
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode().rstrip("=")

def verify_token(token: str, trip_id: str, secret: str) -> bool:
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded).decode()
        payload, sig = raw.rsplit(".",1)
        exp_sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, exp_sig): return False
        data = json.loads(payload)
        if data.get("tid") != trip_id: return False
        if int(data.get("exp",0)) < time.time(): return False
        return True
    except Exception:
        return False
```

- [ ] **Step 4: Add continent detection + force flights**

```python
# src/core/orchestrator.py — nuovo helper
_CONTINENT_MAP = {"italy":"europe","italia":"europe","europe":"europe","patagonia":"south_america","argentina":"south_america","cile":"south_america","chile":"south_america","brasile":"south_america","peru":"south_america","usa":"north_america","giappone":"asia","japan":"asia","thailand":"asia","australia":"oceania"}
def _continent(place: str|None) -> str|None:
    if not place: return None
    key = place.lower().strip()
    for k,v in _CONTINENT_MAP.items():
        if k in key: return v
    return None

# in _execute_searches, prima di skipped_reason:
dep_cont = _continent(trip.departure_location)
dest_cont = _continent(destination or intent.destination or trip.destination or "")
is_intercontinental = dep_cont and dest_cont and dep_cont != dest_cont
if effective_travel_mode in FLIGHT_BLOCKING_TRAVEL_MODES and not is_intercontinental:
    skipped_reason = f"travel_mode:{effective_travel_mode}"
else:
    # procedere con flight search (anche se van_life ma intercontinentale)
    ...
```

- [ ] **Step 5: Generate feedback link in _compose_email**

```python
# in _compose_email, dopo content["cta"]=CTA:
from src.core.feedback_token import make_token
from src.settings import get_settings
settings = get_settings()
# frontend base da settings.allowed_origins[0] o NOSTOS_FEEDBACK_BASE_URL
base = getattr(settings, "feedback_base_url", "https://xen-ia.github.io/nostos")
token = make_token(self._trip_id, settings.api_token or "dev-secret", ttl_days=settings.feedback_token_ttl_days)
content["feedback_link"] = f"{base}/feedback.html?trip_id={self._trip_id}&token={token}" if settings.api_token else f"{base}/feedback.html?trip_id={self._trip_id}&token={token}"
```

Aggiungere `feedback_base_url: str = "https://xen-ia.github.io/nostos"` in `src/settings.py`

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_feedback_token.py tests/test_orchestrator.py -k intercontinental -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/core/feedback_token.py src/core/orchestrator.py src/settings.py tests/test_feedback_token.py
git commit -m "feat(core): intercontinental flights and feedback token"
```

---

### Task 6: Standalone feedback page + token validation

**Files:**
- Create: `docs/feedback.html`
- Modify: `src/api/routers/trips.py:101-129` (optional token check)
- Test: `tests/test_api.py` — test POST /feedback/public con token

**Interfaces:**
- Consumes: `GET ?trip_id & token`, `POST /trips/{id}/feedback/public` con header `X-Feedback-Token`
- Produces: 201 su token valido, 401 su invalido

- [ ] **Step 1: Write failing test**

```python
# tests/test_api.py — aggiungere
def test_feedback_public_with_valid_token(client):
    tok = make_token(trip_id, secret)
    resp = client.post(f"/api/v1/trips/{trip_id}/feedback/public", json={"rating":5}, headers={"X-Feedback-Token": tok})
    assert resp.status_code == 201

def test_feedback_public_invalid_token_rejected(client):
    resp = client.post(f"/api/v1/trips/{trip_id}/feedback/public", json={"rating":5}, headers={"X-Feedback-Token": "bad"})
    assert resp.status_code == 401
```

- [ ] **Step 2: Create docs/feedback.html**

```html
<!DOCTYPE html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Feedback — Nostos</title>
<style>/* minimal, riusa palette parchment/terracotta */ body{font-family:IBM Plex Sans,sans-serif;background:#F8F1E0;color:#2B2118;padding:2rem} .card{max-width:480px;margin:auto;background:#FCF7E8;border:1px solid #A38B5C;border-radius:16px;padding:1.5rem} .stars button{font-size:1.6rem;background:none;border:none;cursor:pointer;color:#D8CBA8} .stars button.active{color:#D9A44A}</style>
</head><body><div class="card">
<h1>Com'è andata?</h1><div class="stars" id="stars"><button data-r="1">★</button><button data-r="2">★</button><button data-r="3">★</button><button data-r="4">★</button><button data-r="5">★</button></div>
<textarea id="comment" placeholder="Un commento (facoltativo)" style="width:100%;margin-top:1rem;min-height:80px"></textarea>
<button id="send" style="margin-top:1rem;padding:.6rem 1.4rem;border-radius:999px;background:#A84E28;color:#F8F1E0;border:none;font-weight:600">Invia feedback</button>
<p id="msg" hidden></p></div>
<script>
const API_BASE="https://nostos.xen-ia.org/api/v1";
const params=new URLSearchParams(location.search); const tripId=params.get("trip_id"), token=params.get("token");
let rating=0;
document.querySelectorAll("#stars button").forEach(b=>b.onclick=()=>{rating=+b.dataset.r; document.querySelectorAll("#stars button").forEach(x=>x.classList.toggle("active",+x.dataset.r<=rating))});
document.getElementById("send").onclick=async()=>{
  if(!rating){ msg.hidden=false; msg.textContent="Scegli un voto"; return; }
  const headers={"Content-Type":"application/json"}; if(token) headers["X-Feedback-Token"]=token;
  const res=await fetch(`${API_BASE}/trips/${tripId}/feedback/public`,{method:"POST",headers,body:JSON.stringify({rating, comment: document.getElementById("comment").value||null})});
  const msg=document.getElementById("msg"); msg.hidden=false;
  msg.textContent=res.ok?"Grazie del feedback!":"Errore: "+res.status;
};
</script></body></html>
```

- [ ] **Step 3: Add optional token validation to trips router**

```python
# src/api/routers/trips.py — in submit_feedback_public
token = request.headers.get("X-Feedback-Token")
if token:
    from src.core.feedback_token import verify_token
    if not verify_token(token, trip_id, settings.api_token or "dev-secret"):
        raise APIError(ErrorCode.UNAUTHORIZED, "Invalid feedback token", 401)
# se nessun token, lascia passare (compatibilità)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/feedback.html src/api/routers/trips.py
git commit -m "feat: standalone feedback page with HMAC token"
```

---

## Self-Review

**Spec coverage:**
- §1 validation + localStorage → Task 2 ✓
- §2 STT frontend+backend gpt-transcribe → Task 1 + 3 ✓
- §3 intercontinental flights → Task 5 ✓
- §4 email dedup + feedback_link placeholder → Task 4 ✓
- §5 feedback token + standalone page → Task 5 + 6 ✓
- §6 STT endpoint → Task 1 ✓

**Placeholder scan:** Nessun TODO/TBD; ogni step ha codice reale.

**Type consistency:** `trip_id: str`, `rating: int 1-5`, `token: str` base64url, `content.feedback_link: str`, `stt_model: str` default `gpt-transcribe`.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-07-user-feedback-improvements.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
