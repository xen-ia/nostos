from typing import Protocol, TypeVar
import json

from anthropic import AsyncAnthropic
from ollama import AsyncClient
from openai import AsyncOpenAI
from pydantic import BaseModel

from src.services.tools import EXTRACT_TOOL_NAME, make_extract_tool, make_ollama_schema, make_responses_tool

T = TypeVar("T", bound=BaseModel)


def build_llm_client(settings) -> "LLMClient":
    from src.core.prompts import get_system_prompt

    provider = settings.llm_provider
    if provider == "gpt":
        return OpenAIClient(
            api_key=settings.openai_api_key,
            model=settings.gpt_model,
            system_prompt=get_system_prompt(),
            timeout=settings.llm_timeout,
        )
    if provider == "ollama":
        return OllamaClient(
            model=settings.ollama_model,
            system_prompt=get_system_prompt(),
            base_url=settings.ollama_url,
            timeout=settings.llm_timeout,
        )
    return AnthropicClient(
        api_key=settings.anthropic_api_key,
        model=settings.claude_model,
        system_prompt=get_system_prompt(),
        timeout=settings.llm_timeout,
    )


class LLMToolUseError(RuntimeError):
    """The model response did not contain the expected tool call."""


def _first(predicate, items):
    for item in items:
        if predicate(item):
            return item
    raise LLMToolUseError("model response missing expected tool call")


class LLMClient(Protocol):
    async def extract[T: BaseModel](self, prompt: str, model: type[T]) -> T:
        """Calls the model with a constrained tool-call and validates the output in type T."""
        ...


class AnthropicClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        system_prompt: str | None = None,
        timeout: float = 120.0,
        client: AsyncAnthropic | None = None,
    ):
        self._client = client or AsyncAnthropic(api_key=api_key, timeout=timeout)
        self._model = model
        self._system_prompt = system_prompt or ""

    async def extract[T: BaseModel](self, prompt: str, model: type[T]) -> T:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=self._system_prompt,
            tools=[make_extract_tool(model)],
            tool_choice={"type": "tool", "name": make_extract_tool(model)["name"]},
            messages=[{"role": "user", "content": prompt}],
        )
        tool_use_block = _first(lambda b: b.type == "tool_use", response.content)
        return model.model_validate(tool_use_block.input)


class OpenAIClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        system_prompt: str | None = None,
        timeout: float = 120.0,
        client: AsyncOpenAI | None = None,
    ):
        self._client = client or AsyncOpenAI(api_key=api_key, timeout=timeout)
        self._model = model
        self._system_prompt = system_prompt or ""

    async def extract[T: BaseModel](self, prompt: str, model: type[T]) -> T:
        response = await self._client.responses.create(
            model=self._model,
            max_output_tokens=1024,
            instructions=self._system_prompt,
            input=prompt,
            tools=[make_responses_tool(model)],
            tool_choice={"type": "function", "name": EXTRACT_TOOL_NAME},
        )
        item = _first(
            lambda i: i.type == "function_call" and i.name == EXTRACT_TOOL_NAME,
            response.output,
        )
        return model.model_validate_json(item.arguments)


class OllamaClient:
    def __init__(
        self,
        model: str,
        system_prompt: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        client: AsyncClient | None = None,
    ):
        self._client = client or AsyncClient(host=base_url, timeout=timeout)
        self._model = model
        self._system_prompt = system_prompt or ""

    async def extract[T: BaseModel](self, prompt: str, model: type[T]) -> T:
        schema = make_ollama_schema(model)
        response = await self._client.chat(
            model=self._model,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n\n"
                        "Reply with ONLY a single JSON object matching this schema. "
                        "No extra text, no code fences.\n"
                        f"Schema: {json.dumps(schema, ensure_ascii=False)}"
                    ),
                },
            ],
            format=schema,
            options={"temperature": 0, "think": False, "num_ctx": 8192},
        )
        return model.model_validate_json(response.message.content)