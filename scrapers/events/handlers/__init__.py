"""
Event Handlers

Handler classes for persisting Test Lab events to database and logging.
"""

from .selector import SelectorResultHandler
from .login import LoginResultHandler
from .extraction import ExtractionResultHandler
from .console import ConsoleLoggerHandler

__all__ = [
    "SelectorResultHandler",
    "LoginResultHandler",
    "ExtractionResultHandler",
    "ConsoleLoggerHandler",
]
