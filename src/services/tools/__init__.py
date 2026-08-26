from typing import TypeVar

from pydantic import BaseModel

from src.services.tools._util import dedupe_cap

__all__ = ["dedupe_cap", "make_extract_tool", "make_responses_tool", "make_ollama_schema"]

T = TypeVar("T", bound=BaseModel)

EXTRACT_TOOL_NAME = "extract"


def make_extract_tool(model: type[T]) -> dict:
    return {"name": EXTRACT_TOOL_NAME, "input_schema": model.model_json_schema()}


def make_responses_tool(model: type[T]) -> dict:
    return {
        "type": "function",
        "name": EXTRACT_TOOL_NAME,
        "description": "Extract the requested fields, constrained to the JSON schema.",
        "parameters": model.model_json_schema(),
    }


def _simplify(node, defs: dict) -> dict:
    """Riduce lo schema pydantic a una forma piatta compatibile con la grammar di llama.cpp."""
    if isinstance(node, dict):
        if "$ref" in node:
            return _simplify(defs[node["$ref"].rsplit("/", 1)[-1]], defs)
        out: dict = {}
        for key, value in node.items():
            if key in ("title", "description", "default", "$defs"):
                continue
            if key == "anyOf":
                types = [v for v in value if v.get("type") is not None]
                if len(types) == 2 and {"type": "null"} in types:
                    inner = next(v for v in types if v.get("type") != "null")
                    out["type"] = [inner["type"], "null"]
            elif key == "properties":
                out[key] = {name: _simplify(prop, defs) for name, prop in value.items()}
            elif key == "items":
                out[key] = _simplify(value, defs)
            else:
                out[key] = value
        return out
    return node


def make_ollama_schema(model: type[T]) -> dict:
    schema = model.model_json_schema()
    return _simplify(schema, schema.get("$defs", {}))