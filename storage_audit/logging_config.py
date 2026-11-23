"""Logging setup: rotating local file log, no network, path-light by default."""

import logging
import logging.handlers
import os


def setup_logging(log_dir, verbose=False, quiet=False):
    """Configure the root logger. Returns the configured logger for the app."""
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "storage_audit.log")

    logger = logging.getLogger("storage_audit")
    logger.setLevel(logging.DEBUG)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else (logging.ERROR if quiet else logging.WARNING))
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(console)

    logger.propagate = False
    return logger
