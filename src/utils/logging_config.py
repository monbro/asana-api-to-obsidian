"""
Centralized logging configuration.

All entry-point scripts call configure_logging() once at startup so that
every module shares a consistent format and level instead of each script
calling basicConfig() independently.
"""

import logging


def configure_logging(
    level: int = logging.INFO,
    fmt: str = "%(asctime)s - %(levelname)s - %(message)s",
) -> logging.Logger:
    """Configure the root logger and return it.

    Args:
        level: Logging level (e.g. logging.DEBUG, logging.INFO).
        fmt:   Log record format string.

    Returns:
        The root logger, ready to use.
    """
    logging.basicConfig(level=level, format=fmt)
    return logging.getLogger()
