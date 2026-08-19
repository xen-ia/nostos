from fastapi import APIRouter, Depends, Request, Response

from src.api.dependencies import get_arq, get_database, get_trip_store
from src.api.errors import APIError, ErrorCode
from src.infrastructure.queue import enqueue_trip
from src.core.schemas import FeedbackRequest, FeedbackResponse, TripCreateRequest, TripResponse, now_iso
from src.api.security import RateLimiter, build_rate_limiter, rate_limit_key, require_api_token
from src.services.trip_store import TripNotFoundError, TripStore

router = APIRouter(prefix="/api/v1/trips", tags=["trips"])


@router.post("/admin/reset", status_code=403)
async def honeypot(_auth: None = Depends(require_api_token)):
    """Decoy endpoint for abuse detection: never valid, always 403."""
    raise APIError(ErrorCode.FORBIDDEN, "Endpoint not found", 403)


@router.post("", response_model=TripResponse, status_code=202)
async def create_trip(
    payload: TripCreateRequest,
    request: Request,
    response: Response,
    store: TripStore = Depends(get_trip_store),
    db=Depends(get_database),
    arq=Depends(get_arq),
):
    if not await db.is_whitelisted(payload.email):
        raise APIError(
            ErrorCode.NOT_WHITELISTED,
            "Email not whitelisted. Request access via the project owners.",
            403,
        )

    settings = request.app.state.settings
    daily = RateLimiter(
        request.app.state.redis,
        max_requests=settings.whitelist_daily_max,
        window_seconds=24 * 60 * 60,
    )
    await daily.check(f"email:{payload.email.lower()}:{now_iso()[:10]}")

    limiter = build_rate_limiter(request)
    await limiter.check(rate_limit_key(request))

    idem = request.headers.get("Idempotency-Key")
    if idem:
        existing_id = await store.trip_id_for_idempotency_key(idem)
        if existing_id is not None:
            return await store.get(existing_id)

    trip = await store.create(payload)
    request.app.state.trips_created += 1
    if idem:
        await store.set_idempotency_key(idem, trip.id)
    await enqueue_trip(arq, trip.id)
    response.headers["Location"] = f"/api/v1/trips/{trip.id}"
    return trip


@router.get("/{trip_id}", response_model=TripResponse)
async def get_trip(
    trip_id: str,
    request: Request,
    store: TripStore = Depends(get_trip_store),
    _auth: None = Depends(require_api_token),
):
    limiter = build_rate_limiter(request)
    await limiter.check(rate_limit_key(request))

    try:
        return await store.get(trip_id)
    except TripNotFoundError:
        raise APIError(ErrorCode.TRIP_NOT_FOUND, "Trip not found or expired", 404)


@router.post(
    "/{trip_id}/feedback",
    response_model=FeedbackResponse,
    status_code=201,
)
async def submit_feedback(
    trip_id: str,
    payload: FeedbackRequest,
    request: Request,
    db=Depends(get_database),
    _auth: None = Depends(require_api_token),
):
    limiter = build_rate_limiter(request)
    await limiter.check(rate_limit_key(request))

    await db.save_feedback(trip_id, payload.rating, payload.comment)
    return FeedbackResponse(
        trip_id=trip_id,
        rating=payload.rating,
        comment=payload.comment,
        created_at=now_iso(),
    )
