import fakeredis.aioredis

from src.services.apis.llm import LLMClient
from src.infrastructure.database import Database
from src.core.schemas import TripCreateRequest, TripResponse
from src.services.trip_store import TripStore


def make_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def make_store(ttl_seconds: int = 86400) -> TripStore:
    return TripStore(redis=make_redis(), ttl_seconds=ttl_seconds)


class FakeLLM(LLMClient):
    """Deterministic in-memory LLM with configurable responses."""

    def __init__(self, response=None, email_response=None, error: Exception | None = None):
        self._response = response
        self._email_response = email_response or response
        self._error = error
        self.calls: list[tuple[str, type]] = []

    async def extract[T: BaseModel](self, prompt: str, model: type[T]) -> T:
        from src.core.models import EmailContent, TripIntent

        self.calls.append((prompt, model))
        if self._error is not None:
            raise self._error
        if model is EmailContent:
            return self._email_response
        if model is TripIntent:
            return self._response
        return self._response


class FakeEmailSender:
    def __init__(self):
        self.sent: list[dict] = []
        self.error: Exception | None = None

    async def send(self, to: str, subject: str, body: str, html: str | None = None, timeout: float = 60.0) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append({"to": to, "subject": subject, "body": body, "html": html})


class FakeDatabase(Database):
    def __init__(self):
        self.saved: list[dict] = []
        self.status: dict[str, str] = {}
        self.feedback: tuple | None = None
        self.error: Exception | None = None

    async def save_trip_history(self, **kwargs) -> None:
        if self.error is not None:
            raise self.error
        self.saved.append(kwargs)

    async def update_status(self, trip_id: str, status: str) -> None:
        self.status[trip_id] = status

    async def save_feedback(self, trip_id: str, rating: int, comment: str | None) -> None:
        self.feedback = (trip_id, rating, comment)


def make_trip(**overrides) -> TripResponse:
    payload = TripCreateRequest(
        email="test@example.com",
        destination="Tokyo",
        start_date="2026-09-01",
        end_date="2026-09-10",
        flexible_dates=True,
        travelers_count=2,
        travelers_type="coppia",
        budget_range="medio",
        departure_location="MXP",
        free_text="ci piace il cibo locale",
    )
    data = payload.model_dump()
    data.update(overrides)
    return TripResponse(
        id=data.pop("id", "trip-1"),
        status=data.pop("status", "pending"),
        received_at=data.pop("received_at", "2026-01-01T00:00:00+00:00"),
        result=data.pop("result", None),
        **data,
    )
