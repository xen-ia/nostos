import asyncio
import io

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse
from openai import OpenAI

from src.api.errors import APIError, ErrorCode
from src.api.security import RateLimiter, rate_limit_key
from src.settings import Settings, get_settings

router = APIRouter(prefix="/api/v1", tags=["stt"])

ALLOWED_CT = {
    "audio/webm",
    "audio/mp4",
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/m4a",
    "audio/ogg",
    "video/webm",
}


@router.post("/stt")
async def speech_to_text(
    request: Request,
    audio: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
):
    limiter = RateLimiter(request.app.state.redis, max_requests=10, window_seconds=60)
    await limiter.check(rate_limit_key(request))
    if not settings.openai_api_key:
        raise APIError(ErrorCode.INTERNAL_ERROR, "STT not configured", 503)
    # early size check via UploadFile.size if available
    if audio.size is not None and audio.size > settings.stt_max_mb * 1024 * 1024:
        raise APIError(ErrorCode.BAD_REQUEST, f"File too large >{settings.stt_max_mb}MB", 413)
    ctype_raw = (audio.content_type or "").lower()
    ctype = ctype_raw.split(";")[0].strip()
    if ctype not in ALLOWED_CT and not ctype.startswith("audio/"):
        raise APIError(ErrorCode.BAD_REQUEST, "Invalid audio type", 400)
    data = await audio.read()
    if len(data) > settings.stt_max_mb * 1024 * 1024:
        raise APIError(ErrorCode.BAD_REQUEST, f"File too large >{settings.stt_max_mb}MB", 413)
    if len(data) == 0:
        raise APIError(ErrorCode.BAD_REQUEST, "Empty audio file", 400)

    client = OpenAI(api_key=settings.openai_api_key)

    def _call():
        f = io.BytesIO(data)
        f.name = audio.filename or "audio.webm"
        return client.audio.transcriptions.create(model=settings.stt_model, file=f, language="it")

    try:
        resp = await asyncio.to_thread(_call)
    except APIError:
        raise
    except Exception as e:
        raise APIError(ErrorCode.INTERNAL_ERROR, f"Transcription failed: {e}", 502)
    return JSONResponse({"text": resp.text})
