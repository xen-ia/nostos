"""Decision clients.

Internal contract (kept stable for the router and the scorer):

    await client.decide(state: dict, questions: dict) -> {"model": str, "answers": {name: {...}}}

`answers` uses the System One shape: ``{"type": "noul", "noul": p}`` for a
boolean/predicate and ``{"type": "choice", "choice": v, "confidence": c}`` for
a pick. `JevDecisionClient` speaks that format natively; `OpenAIDecisionClient`
adapts OpenAI's `/v1/decisions` (predicate/choice/score) to and from it.
"""
import json
import logging

import httpx

logger = logging.getLogger("nostos.decisions")

SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
OPENAI_DECISIONS_URL = "https://api.openai.com/v1/decisions"

JEV_PINNED_MODEL = "jev-1.13.0"
OPENAI_PINNED_MODEL = "gpt-6-luna"

PINNED_MODELS = {"jev": JEV_PINNED_MODEL, "openai": OPENAI_PINNED_MODEL}


def effective_decision_model(provider: str, model: str = "") -> str:
    """Model to use, falling back to the provider's pinned model."""
    return model or PINNED_MODELS.get(provider, "")


def apply_threshold(prob: float) -> str:
    if prob >= 0.85:
        return "auto"
    if prob >= 0.60:
        return "review"
    return "fallback"


class DecisionError(RuntimeError):
    pass


# Back-compat: the router/scoring tests and callers import JevError.
JevError = DecisionError


def _to_openai_questions(questions: dict) -> list[dict]:
    """System One questions map -> OpenAI decisions questions list."""
    out: list[dict] = []
    for name, spec in questions.items():
        spec = spec or {}
        item: dict = {"name": name, "instructions": spec.get("instructions", "")}
        kind = spec.get("type", "noul")
        if kind == "choice":
            item["type"] = "choice"
            item["choices"] = [
                {"value": value, "description": desc}
                for value, desc in (spec.get("criteria") or {}).items()
            ]
        else:
            # noul (and anything unmapped) is a yes/no predicate.
            item["type"] = "predicate"
        out.append(item)
    return out


def _from_openai_answers(answers: list) -> dict:
    """OpenAI answers list -> System One answers map (refusals dropped)."""
    out: dict = {}
    for answer in answers or []:
        if not isinstance(answer, dict):
            continue
        name = answer.get("name")
        if not name:
            continue
        kind = answer.get("type")
        if kind == "predicate":
            out[name] = {"type": "noul", "noul": answer.get("probability", 0.0)}
        elif kind == "choice":
            out[name] = {"type": "choice", "choice": answer.get("choice"),
                         "confidence": answer.get("confidence", 0.0)}
    return out


class JevDecisionClient:
    def __init__(self, api_key: str, model: str = JEV_PINNED_MODEL, timeout: float = 5.0,
                 client: httpx.AsyncClient | None = None):
        self._api_key = api_key
        self._model = model or JEV_PINNED_MODEL
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
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            body = (exc.response.text[:300] if exc.response is not None else "")
            logger.warning("jev decide HTTP %s: %s", status, body)
            raise DecisionError(f"jev decide failed: HTTP {status}: {body}") from exc
        except DecisionError:
            raise
        except Exception as exc:
            raise DecisionError(f"jev decide failed: {type(exc).__name__}: {exc}") from exc
        return {"model": data.get("model", self._model), "answers": data.get("answers", data)}

    async def close(self) -> None:
        """Release the owned httpx.AsyncClient. Safe to call more than once."""
        try:
            await self._client.aclose()
        except Exception:
            pass

    # Alias for httpx-style lifespan naming.
    aclose = close


class OpenAIDecisionClient:
    def __init__(self, api_key: str, model: str = OPENAI_PINNED_MODEL, timeout: float = 5.0,
                 client: httpx.AsyncClient | None = None):
        self._api_key = api_key
        self._model = model or OPENAI_PINNED_MODEL
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def decide(self, state: dict, questions: dict) -> dict:
        payload = {
            "model": self._model,
            "input": json.dumps(state, ensure_ascii=False, indent=2),
            "questions": _to_openai_questions(questions),
        }
        try:
            resp = await self._client.post(
                OPENAI_DECISIONS_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            body = (exc.response.text[:300] if exc.response is not None else "")
            logger.warning("openai decide HTTP %s: %s", status, body)
            raise DecisionError(f"openai decide failed: HTTP {status}: {body}") from exc
        except DecisionError:
            raise
        except Exception as exc:
            raise DecisionError(f"openai decide failed: {type(exc).__name__}: {exc}") from exc
        return {"model": data.get("model", self._model),
                "answers": _from_openai_answers(data.get("answers", []))}

    async def close(self) -> None:
        """Release the owned httpx.AsyncClient. Safe to call more than once."""
        try:
            await self._client.aclose()
        except Exception:
            pass

    # Alias for httpx-style lifespan naming.
    aclose = close


def build_decision_client(settings):
    """Pick the decision client for the configured provider.

    Returns None when the provider is disabled (`llm-fallback`) or its API key
    is missing, in which case the orchestrator keeps the LLM path.
    """
    provider = getattr(settings, "decision_provider", "llm-fallback")
    model = getattr(settings, "decision_model", "") or ""
    timeout = getattr(settings, "decision_timeout", 5.0)
    if provider == "jev":
        if not getattr(settings, "typesafe_api_key", ""):
            return None
        return JevDecisionClient(api_key=settings.typesafe_api_key,
                                 model=effective_decision_model("jev", model), timeout=timeout)
    if provider == "openai":
        if not getattr(settings, "openai_api_key", ""):
            return None
        return OpenAIDecisionClient(api_key=settings.openai_api_key,
                                    model=effective_decision_model("openai", model), timeout=timeout)
    return None
