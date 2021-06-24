"""The logging package"""

from log.log import *
from log.CustomTimedFileHandler import TimedFileHandler


__all__ = [
    "log",
    "debug",
    "info",
    "warning",
    "error",
    "exception",
    "critical",
    "fatal",
    "getLogger",
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
    "FATAL",
]
