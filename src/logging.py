"""Shared logging configuration for both the API and the worker process."""
import logging

from rich.logging import RichHandler


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(rich_tracebacks=True, show_time=True, show_path=True, markup=False)],
        force=True,
    )
