import pytest

from src.services.apis.llm import AnthropicClient, LLMToolUseError, OpenAIClient
from src.core.models import TripIntent


class _FakeResponse:
    def __init__(self, content, output=None):
        self.content = content
        self.output = output if output is not None else content


class _Block:
    def __init__(self, btype, **kwargs):
        self.type = btype
        self.__dict__.update(kwargs)


def test_anthropic_missing_tool_use_raises_descriptive_error():
    client = AnthropicClient(api_key="x", model="m")

    class FakeMessages:
        async def create(self, **kwargs):
            return _FakeResponse([_Block("text", text="no tool call here")])

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    client._client = FakeAnthropic()
    with pytest.raises(LLMToolUseError):
        import asyncio
        asyncio.run(client.extract("prompt", TripIntent))


def test_anthropic_extract_parses_tool_use():
    client = AnthropicClient(api_key="x", model="m")

    class FakeMessages:
        async def create(self, **kwargs):
            return _FakeResponse([_Block("tool_use", input={"destination": "Tokyo"})])

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    client._client = FakeAnthropic()
    import asyncio
    intent = asyncio.run(client.extract("prompt", TripIntent))
    assert intent.destination == "Tokyo"


def test_openai_missing_function_call_raises_descriptive_error():
    client = OpenAIClient(api_key="x", model="m")

    class FakeResponses:
        async def create(self, **kwargs):
            return _FakeResponse([_Block("message", role="assistant", content="nothing")])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    client._client = FakeOpenAI()
    with pytest.raises(LLMToolUseError):
        import asyncio
        asyncio.run(client.extract("prompt", TripIntent))
