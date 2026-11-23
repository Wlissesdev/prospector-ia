"""Logs locais rotativos, sem segredos."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from prospector.config import AppPaths


def configure_logging(paths: AppPaths) -> logging.Logger:
    """Configura o logger uma vez por processo."""
    paths.ensure_exists()
    logger = logging.getLogger("prospector")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    handler = RotatingFileHandler(
        paths.logs / "prospector.log", encoding="utf-8", maxBytes=1_000_000, backupCount=5
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger
