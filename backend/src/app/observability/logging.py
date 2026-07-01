"""Central logging configuration."""

import logging
import logging.config
from typing import Any


def configure_logging(level: str, json_logs: bool) -> None:
    formatter = "json" if json_logs else "console"
    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "console": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
            "json": {
                "()": "pythonjsonlogger.json.JsonFormatter",
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": formatter,
                "stream": "ext://sys.stdout",
            }
        },
        "root": {"handlers": ["default"], "level": level},
    }
    logging.config.dictConfig(config)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
