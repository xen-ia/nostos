import uuid
from datetime import datetime, timezone
from typing import Optional, Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pydantic import BaseModel, Field

from src.core.redis_client import redis_client

app = FastAPI(title="Nostos API - test", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://xen-ia.github.io",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class TripRequest(BaseModel):
    destination: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    flexible_dates: bool = False
    travelers_count: int = Field(1, ge=1)
    travelers_type: Optional[Literal["solo", "coppia", "famiglia", "amici", "gruppo"]] = None
    budget_range: Optional[Literal["economico", "medio", "alto", "no-limit"]] = None
    departure_location: Optional[str] = None
    free_text: str = ""


@app.post("/trips")
async def save_trip(payload: TripRequest):
    record_id = str(uuid.uuid4())
    await redis_client.hset(
        f"trip:{record_id}",
        mapping={
            "destination": payload.destination or "",
            "start_date": payload.start_date or "",
            "end_date": payload.end_date or "",
            "flexible_dates": str(payload.flexible_dates),
            "travelers_count": payload.travelers_count,
            "travelers_type": payload.travelers_type or "",
            "budget_range": payload.budget_range or "",
            "departure_location": payload.departure_location or "",
            "free_text": payload.free_text,
            "received_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {"id": record_id, **payload.model_dump()}


if __name__ == "__main__":
    uvicorn.run(
        "main:app", 
        host="127.0.0.1", 
        port=3072, 
        reload=True
    )