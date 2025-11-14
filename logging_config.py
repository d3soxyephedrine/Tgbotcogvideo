"""
Centralized logging configuration for the application.

This module should be imported and initialized once at application startup.
Other modules should only call logging.getLogger(__name__) to get their logger.
"""

import logging
import sys


def setup_logging(level=logging.DEBUG):
    """
    Configure logging once for the entire application.

    Args:
        level: Logging level (default: DEBUG)

    This should be called once at application startup, before any other modules
    that use logging are imported.
    """
    # Configure root logger
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    # Set specific loggers to appropriate levels to reduce noise
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

    # Get the root logger for initial message
    logger = logging.getLogger(__name__)
    logger.info("Centralized logging configuration initialized")

    return logging.getLogger()


def get_logger(name):
    """
    Get a logger instance for a module.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)
