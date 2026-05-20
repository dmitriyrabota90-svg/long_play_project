from __future__ import annotations

import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config.settings import Settings, get_settings


class UtcFormatter(logging.Formatter):
    converter = time.gmtime


def setup_logging(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = UtcFormatter(
        fmt="%(asctime)sZ %(levelname)s %(name)s %(process)d %(threadName)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        handlers=[console_handler, file_handler],
        force=True,
    )
