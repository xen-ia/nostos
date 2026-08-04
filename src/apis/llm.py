from typing import Protocol

from anthropic import AsyncAnthropic


class LLMClient(Protocol):
    async def extract_json(self, prompt: str, schema: dict) -> dict:
        """Chiama il modello, ritorna un dizionario conforme allo schema JSON dato."""
        ...

    async def generate_text(self, prompt: str) -> str:
        """Genera testo libero, non vincolato a uno schema — per output editoriali."""
        ...


class AnthropicClient:
    def __init__(self, api_key: str, model: str):
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def extract_json(self, prompt: str, schema: dict) -> dict:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            tools=[{"name": "extract", "input_schema": schema}],
            tool_choice={"type": "tool", "name": "extract"},
            messages=[{"role": "user", "content": prompt}],
        )
        tool_use_block = next(b for b in response.content if b.type == "tool_use")
        return tool_use_block.input
    
    
    async def generate_text(self, prompt: str) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text_block = next(b for b in response.content if b.type == "text")
        return text_block.text