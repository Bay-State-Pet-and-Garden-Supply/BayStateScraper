"""
Console Logger Handler

Logs Test Lab events to console for debugging and development.
"""

from __future__ import annotations

import logging

from scrapers.events.base import BaseEvent
from scrapers.events.selector import SelectorValidationEvent
from scrapers.events.login import LoginStatusEvent
from scrapers.events.extraction import ExtractionResultEvent

logger = logging.getLogger(__name__)


class ConsoleLoggerHandler:
    """Handler that logs events to console."""

    def handle(self, event: BaseEvent) -> None:
        """Log event to console."""
        if isinstance(event, SelectorValidationEvent):
            logger.info(f"[SELECTOR] {event.scraper}/{event.sku}: {event.selector_name} = {event.status}")
        elif isinstance(event, LoginStatusEvent):
            logger.info(f"[LOGIN] {event.scraper}/{event.sku}: status={event.status}")
        elif isinstance(event, ExtractionResultEvent):
            logger.info(f"[EXTRACTION] {event.scraper}/{event.sku}: {event.field_name} = {event.status}")
        else:
            logger.info(f"[EVENT] {event.event_type}: {event.to_dict()}")
