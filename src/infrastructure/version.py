"""Application version, sourced from pyproject.toml."""

import functools
import tomllib
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _PROJECT_ROOT / "pyproject.toml"


@functools.lru_cache(maxsize=1)
def get_app_version() -> str:
    """Return the package version (e.g. "0.1.0") from pyproject.toml."""
    with _PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    return data["project"]["version"]