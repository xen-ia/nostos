# User Feedback Improvements — Design Spec

**Date**: 2026-09-07  
**Status**: Approved for implementation  
**Scope**: Frontend, email template, orchestrator, API

---

## Overview

Address 6 categories of user feedback from production usage:

1. **Incomplete submissions trigger emails** — no client/server validation
2. **Page refresh loses trip tracking** — `trip_id` only in memory
3. **Missing flight info for intercontinental trips** — van_life blocks flights
4. **No feedback link in email** — can't give feedback after refresh
5. **Email output issues** — redundancy, unclickable cards, repetitive sections
6. **STT for free_text** — microphone button to dictate trip description

---

## Section 1: Frontend — Form Validation & Trip Persistence

### Changes to `docs/index.html`

#### 1.1 Client-side Validation
- Require: `email`, `start_date`, and at least one of `destination` OR `free_text`
- Show inline error messages on invalid submit
- Disable submit button until valid

#### 1.2 Persist `trip_id` in `localStorage`
- On successful `POST /trips` (202): store `trip_id` + timestamp under key `nostos_active_trip`
- On page load: check `localStorage` for active trip
  - If `pending`/`running` → resume polling via `GET /trips/{id}/status/public`
  - If `done` → show feedback widget pre-loaded with trip
  - If `error` → show error + "nuova ricerca" button
- Clear `localStorage` only after feedback sent OR explicit "Nuova ricerca" click

#### 1.3 "Nuova ricerca" Button
- Show in status area when active trip exists
- Click → clear `localStorage`, reset form, hide status/feedback

---

## Section 2: Frontend — STT (OpenAI `gpt-transcribe`)

### Changes to `docs/index.html`
- Add microphone icon button next to `free_text` textarea
- On click: start `MediaRecorder` (audio/webm) → record → on stop, `POST /api/v1/stt` with audio blob
- Append returned transcript to `free_text` textarea
- Show recording indicator (pulsing mic icon)

### New Backend Endpoint: `POST /api/v1/stt`
- **File**: `src/api/routers/stt.py`
- Accepts `multipart/form-data` with `audio` file (max 25MB, webm/mp4/m4a/mp3/wav)
- Calls OpenAI `gpt-transcribe` model ($0.0045/min)
- Returns `{ "text": "transcript" }`
- Rate-limited by IP (public, stricter than API)
- Requires `NOSTOS_OPENAI_API_KEY` in settings

---

## Section 3: Orchestrator — Intercontinental Flight Detection

### Changes to `src/core/orchestrator.py`

#### 3.1 Continent Detection
- In `_execute_searches`: geocode `departure_location` and `destination` to continents
- Simple mapping: country/region → continent (can use LLM call or static dict)
- If continents differ → **force flight search** regardless of `travel_mode`

#### 3.2 Flight Search for Intercontinental
- Use `departure_location` to infer IATA codes (LLM extraction or static map)
- Search flights from departure continent hubs to destination continent hubs
- Include as separate resource group "Come arrivare" in email (distinct from "Come muoversi in loco")

#### 3.3 Email Content
- Add `travel_mode` = "intercontinental" flag to `EmailContent`
- Render flights in dedicated section before local mobility

---

## Section 4: Email Template — Fix Redundancy & Clickability

### Changes to `src/services/templates/email.html` + `src/services/apis/email.py`

#### 4.1 Remove Duplicate Mobility Rendering
- In `build_html_email`: skip `_render_mobility_inline` when `travel_mode` is set (not "fixed")
- Mobility shown ONLY in travel_mode_block (e.g., "Mezzi: auto, van" inside "Vita in van" card)

#### 4.2 Fix Card Clickability
- Verify all resource cards use `<a href="...">` wrapping ENTIRE card (not just title)
- Test in Gmail/Outlook/Apple Mail

#### 4.3 Simplify Travel Mode Labels
- Use consistent Italian from `_TRAVEL_MODE_BLOCKS`:
  - `road_trip` → "Come muoversi in loco"
  - `van_life` → "Vita in van"
  - `sailing` → "Navigazione"
  - `intercontinental` → "Come arrivare" (new)

#### 4.4 Add Feedback CTA Link
- New placeholder `$feedback_link` in template
- Renders as button: "Lascia un feedback" → `https://<frontend>/feedback?trip_id=<id>&token=<hmac>`

---

## Section 5: Email Feedback Link & Standalone Feedback Page

### 5.1 Orchestrator: Generate Signed Token
- In `_compose_email`: create HMAC token for feedback
- Payload: `trip_id` + `expires_at` (7 days)
- Secret: `NOSTOS_API_TOKEN` (existing)
- Include in `EmailContent.feedback_link`

### 5.2 Standalone Feedback Page: `docs/feedback.html`
- Minimal HTML (no framework, ~50 lines)
- Reads `trip_id` + `token` from URL query params
- Validates token via `POST /trips/{trip_id}/feedback/public` (includes token in header)
- Shows 5-star rating + comment textarea + submit
- Success → "Grazie!" message

### 5.3 API: Token Validation
- In `src/api/routers/trips.py`: `submit_feedback_public`
- Add dependency to validate HMAC token from `X-Feedback-Token` header
- Reject invalid/expired tokens (401)

---

## Section 6: Backend — STT Endpoint

### New File: `src/api/routers/stt.py`
```python
@router.post("/stt")
async def speech_to_text(
    audio: UploadFile = File(...),
    request: Request,
    settings: Settings = Depends(get_settings),
):
    # Validate content-type, size
    # Call OpenAI gpt-transcribe
    # Return {"text": transcript}
```

### Integration
- Include router in `src/api/main.py`
- Add `NOSTOS_OPENAI_API_KEY` to `src/settings.py`
- Rate limiter: 10 req/min per IP (configurable)

---

## Data Flow Summary

```
User fills form → [validation] → POST /trips → 202 + trip_id
                                    ↓
                          localStorage.setItem(trip_id)
                                    ↓
                          Worker picks up job
                                    ↓
                    Orchestrator: intent → research → email
                    - Detects intercontinental → forces flights
                    - Generates feedback HMAC token
                    - Sends email with feedback_link
                                    ↓
                    User clicks feedback_link → feedback.html
                                    ↓
                    POST /feedback/public (with token) → 201
                                    ↓
                    localStorage cleared
```

---

## Configuration

| Setting | Description | Default |
|---------|-------------|---------|
| `NOSTOS_OPENAI_API_KEY` | OpenAI key for STT | required |
| `NOSTOS_STT_MODEL` | Model to use | `gpt-transcribe` |
| `NOSTOS_STT_MAX_MB` | Max audio upload size | 25 |
| `NOSTOS_FEEDBACK_TOKEN_TTL_DAYS` | Feedback link expiry | 7 |

---

## Testing Checklist

- [ ] Form validation blocks submit with missing required fields
- [ ] Page refresh during `running` → resumes polling automatically
- [ ] Page refresh after `done` → shows feedback widget
- [ ] "Nuova ricerca" clears state completely
- [ ] STT button records → transcribes → appends to textarea
- [ ] Italy → Patagonia trip includes flight options in email
- [ ] Email: no duplicate "Mezzi" lines, cards clickable
- [ ] Email feedback link opens feedback.html, submits successfully
- [ ] Expired/invalid feedback token rejected
- [ ] STT rate limiting works