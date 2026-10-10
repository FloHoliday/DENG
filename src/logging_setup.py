"""Standard logging to stderr and, optionally, to a file under logs/."""

import logging
from pathlib import Path


def setup_logging(level: str = "INFO", log_file: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    # One line per unit comes from the pipeline itself; per-request lines would only repeat it.
    logging.getLogger("httpx").setLevel(logging.WARNING)
