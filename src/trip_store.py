import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel, Field
from redis.asyncio import Redis


class TripStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class TripCreateRequest(BaseModel):
    email: str 
    destination: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    flexible_dates: bool = False
    travelers_count: int = Field(1, ge=1)
    travelers_type: Optional[Literal["solo", "coppia", "famiglia", "amici", "gruppo"]] = None
    budget_range: Optional[Literal["economico", "medio", "alto", "no-limit"]] = None
    departure_location: Optional[str] = None
    free_text: str = ""


class TripResponse(TripCreateRequest):
    id: str
    status: TripStatus
    received_at: str
    result: Optional[str] = None


class TripNotFoundError(Exception):
    pass


class TripStore:
    def __init__(self, redis: Redis, ttl_seconds: int):
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def _key(trip_id: str) -> str:
        return f"trip:{trip_id}"

    async def create(self, payload: TripCreateRequest) -> TripResponse:
        trip_id = str(uuid.uuid4())
        received_at = datetime.now(timezone.utc).isoformat()

        record = {
            "status": TripStatus.PENDING.value,
            "email": payload.email,
            "destination": payload.destination or "",
            "start_date": payload.start_date or "",
            "end_date": payload.end_date or "",
            "flexible_dates": str(payload.flexible_dates),
            "travelers_count": payload.travelers_count,
            "travelers_type": payload.travelers_type or "",
            "budget_range": payload.budget_range or "",
            "departure_location": payload.departure_location or "",
            "free_text": payload.free_text,
            "received_at": received_at,
        }
        key = self._key(trip_id)
        await self._redis.hset(key, mapping=record)
        await self._redis.expire(key, self._ttl)

        return self._to_response(trip_id, record)

    async def get(self, trip_id: str) -> TripResponse:
        data = await self._redis.hgetall(self._key(trip_id))
        if not data:
            raise TripNotFoundError(trip_id)
        return self._to_response(trip_id, data)

    async def claim(self, trip_id: str, ttl_seconds: int) -> bool:
        lock_key = f"{self._key(trip_id)}:lock"
        claimed = await self._redis.set(lock_key, "1", nx=True, ex=ttl_seconds)
        return bool(claimed)

    async def update_status(self, trip_id: str, status: TripStatus, result: Optional[str] = None) -> None:
        mapping = {"status": status.value}
        if result is not None:
            mapping["result"] = result
        await self._redis.hset(self._key(trip_id), mapping=mapping)

    @staticmethod
    def _to_response(trip_id: str, data: dict) -> TripResponse:
        return TripResponse(
            id=trip_id,
            status=TripStatus(data["status"]),
            email=data.get("email", ""),
            destination=data.get("destination") or None,
            start_date=data.get("start_date") or None,
            end_date=data.get("end_date") or None,
            flexible_dates=str(data.get("flexible_dates")) == "True",
            travelers_count=int(data.get("travelers_count", 1)),
            travelers_type=data.get("travelers_type") or None,
            budget_range=data.get("budget_range") or None,
            departure_location=data.get("departure_location") or None,
            free_text=data.get("free_text", ""),
            received_at=data.get("received_at", ""),
            result=data.get("result") or None,
        )