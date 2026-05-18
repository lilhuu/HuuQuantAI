"""Logging helper."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logger(
    level: str = "INFO",
    name: str = "auto_trader",
    file_path: str = "logs/trading.log",
    max_file_size: int = 10_485_760,
    backup_count: int = 5,
) -> logging.Logger:
    """Configure console and rotating file logging."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        file_path,
        maxBytes=max_file_size,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    if not root_logger.handlers:
        root_logger.addHandler(stream_handler)
        root_logger.addHandler(file_handler)

    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    return logger
