"""
Test Lab Event System

Real-time event emission system for Test Lab updates.
Provides event classes and event emitter for scraper test runs.
"""

from .base import BaseEvent
from .selector import SelectorValidationEvent
from .login import LoginStatusEvent
from .extraction import ExtractionResultEvent
from .emitter import EventEmitter
from . import websocket_server
from . import handlers

__all__ = [
    "BaseEvent",
    "SelectorValidationEvent",
    "LoginStatusEvent",
    "ExtractionResultEvent",
    "EventEmitter",
    "websocket_server",
    "handlers",
]
