"""Jev DecisionClient: POST /v1/systemone, state + questions."""
import httpx

SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
PINNED_MODEL = "jev-1.13.0"


def apply_threshold(prob: float) -> str:
    if prob >= 0.85:
        return "auto"
    if prob >= 0.60:
        return "review"
    return "fallback"


class JevError(RuntimeError):
    pass


class JevClient:
    def __init__(self, api_key: str, model: str = PINNED_MODEL, timeout: float = 5.0, client: httpx.AsyncClient | None = None):
        self._api_key = api_key
        self._model = model or PINNED_MODEL
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def decide(self, state: dict, questions: dict) -> dict:
        try:
            resp = await self._client.post(
                SYSTEMONE_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "state": state, "questions": questions},
            )
            resp.raise_for_status()
            data = resp.json()
        except JevError:
            raise
        except Exception as exc:
            raise JevError(f"jev decide failed: {type(exc).__name__}: {exc}") from exc
        return {"model": data.get("model", self._model), "answers": data.get("answers", data)}

    async def close(self) -> None:
        """Release the owned httpx.AsyncClient. Safe to call more than once."""
        try:
            await self._client.aclose()
        except Exception:
            pass

    # Alias for httpx-style lifespan naming.
    aclose = close


def build_decision_client(settings) -> JevClient | None:
    if getattr(settings, "decision_provider", "llm-fallback") != "jev":
        return None
    if not getattr(settings, "typesafe_api_key", ""):
        return None
    return JevClient(api_key=settings.typesafe_api_key, model=settings.decision_model, timeout=settings.decision_timeout)
