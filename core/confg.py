import logging
import sys

from core.logging import InterceptHandler
from loguru import logger

from starlette.config import Config

config = Config(".env")

DEBUG: bool = config("DEBUG", cast=bool, default=False)

LOGGING_LEVEL = logging.DEBUG if DEBUG else logging.INFO

logging.basicConfig(
    handlers=[InterceptHandler(level=LOGGING_LEVEL)], level=LOGGING_LEVEL
)
logger.configure(handlers=[{"sink": sys.stderr, "level": LOGGING_LEVEL}])