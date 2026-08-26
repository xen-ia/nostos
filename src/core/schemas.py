"""Network API layer: request/response DTOs and trip status."""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class TripStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class TripCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    destination: Optional[str] = Field(default=None, max_length=200)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    flexible_dates: bool = False
    travelers_count: int = Field(1, ge=1, le=20)
    travelers_type: Optional[Literal["solo", "coppia", "famiglia", "amici", "gruppo"]] = None
    departure_location: Optional[str] = Field(default=None, max_length=200)
    free_text: str = Field(default="", max_length=5000)
    budget_amount: Optional[str] = Field(default=None, max_length=200)
    travel_mode: Optional[Literal["volo", "treno", "auto", "van", "indifferente"]] = None
    stay_preference: Optional[Literal["hotel", "b&b", "agriturismo", "glamping", "camping", "indifferente"]] = None

    @field_validator("start_date", "end_date")
    @classmethod
    def _validate_date(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value == "":
            return value
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("date must be ISO 8601 (YYYY-MM-DD)") from exc
        return value

    @model_validator(mode="after")
    def _check_date_range(self) -> "TripCreateRequest":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class TripResponse(TripCreateRequest):
    id: str
    status: TripStatus
    received_at: str
    result: Optional[str] = None


class FeedbackRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=2000)


class FeedbackResponse(FeedbackRequest):
    trip_id: str
    created_at: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
