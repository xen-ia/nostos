from pathlib import Path

_PROMPTS_PATH = Path(__file__).parent / "system_prompt.md"

SYSTEM_PROMPT = _PROMPTS_PATH.read_text(encoding="utf-8")