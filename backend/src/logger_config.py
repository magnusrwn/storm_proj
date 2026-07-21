import logging
import os
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler


def configure_logging(log_file: Path | None = None) -> None:
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
    ]

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)

        handlers.append(
            RotatingFileHandler(
                log_file,
                maxBytes=5_000_000,
                backupCount=3,
                encoding="utf-8",
            )
        )

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )