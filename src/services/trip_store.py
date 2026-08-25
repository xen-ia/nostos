import uuid
from typing import Optional

from redis.asyncio import Redis

from src.core.schemas import TripCreateRequest, TripResponse, TripStatus, now_iso


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
        received_at = now_iso()

        record = {
            "status": TripStatus.PENDING.value,
            "email": payload.email,
            "destination": payload.destination or "",
            "start_date": payload.start_date or "",
            "end_date": payload.end_date or "",
            "travelers_count": payload.travelers_count,
            "travelers_type": payload.travelers_type or "",
            "budget_range": payload.budget_range or "",
            "departure_location": payload.departure_location or "",
            "free_text": payload.free_text,
            "travelers_composition": payload.travelers_composition or "",
            "budget_amount": payload.budget_amount or "",
            "travel_mode": payload.travel_mode or "",
            "stay_preference": payload.stay_preference or "",
            "received_at": received_at,
        }
        key = self._key(trip_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hset(key, mapping=record)
            pipe.expire(key, self._ttl)
            await pipe.execute()

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

    async def renew(self, trip_id: str, ttl_seconds: int) -> None:
        lock_key = f"{self._key(trip_id)}:lock"
        await self._redis.expire(lock_key, ttl_seconds)

    async def release(self, trip_id: str) -> None:
        lock_key = f"{self._key(trip_id)}:lock"
        await self._redis.delete(lock_key)

    async def update_status(self, trip_id: str, status: TripStatus, result: Optional[str] = None) -> None:
        mapping = {"status": status.value}
        if result is not None:
            mapping["result"] = result
        await self._redis.hset(self._key(trip_id), mapping=mapping)

    async def trip_id_for_idempotency_key(self, key: str) -> Optional[str]:
        return await self._redis.get(f"idem:{key}")

    async def set_idempotency_key(self, key: str, trip_id: str) -> None:
        await self._redis.set(f"idem:{key}", trip_id, nx=True, ex=self._ttl)

    @staticmethod
    def _to_response(trip_id: str, data: dict) -> TripResponse:
        return TripResponse(
            id=trip_id,
            status=TripStatus(data["status"]),
            email=data.get("email", ""),
            destination=data.get("destination") or None,
            start_date=data.get("start_date") or None,
            end_date=data.get("end_date") or None,
            travelers_count=int(data.get("travelers_count", 1)),
            travelers_type=data.get("travelers_type") or None,
            budget_range=data.get("budget_range") or None,
            departure_location=data.get("departure_location") or None,
            free_text=data.get("free_text", ""),
            received_at=data.get("received_at", ""),
            result=data.get("result") or None,
            travelers_composition=data.get("travelers_composition") or None,
            budget_amount=data.get("budget_amount") or None,
            travel_mode=data.get("travel_mode") or None,
            stay_preference=data.get("stay_preference") or None,
        )