"""
Selector Result Handler

Handles selector validation events and persists them to the database.
"""

from __future__ import annotations

from typing import Any, Protocol

from scrapers.events.selector import SelectorValidationEvent


class SupabaseClient(Protocol):
    """Protocol for Supabase client."""

    def table(self, name: str) -> Any: ...


class SelectorResultHandler:
    """Handler for selector validation events."""

    def __init__(self, supabase: SupabaseClient) -> None:
        """Initialize handler with Supabase client."""
        self.supabase = supabase

    def handle(self, event: SelectorValidationEvent) -> None:
        """Persist selector validation event to database."""
        data = {
            "test_run_id": getattr(event, "test_run_id", None),
            "scraper_id": getattr(event, "scraper_id", None),
            "scraper": event.scraper,
            "sku": event.sku,
            "selector_name": event.selector_name,
            "selector_value": event.selector_value,
            "status": event.status,
            "duration_ms": event.duration_ms,
            "error_message": event.error_message,
        }

        self.supabase.table("scraper_selector_results").insert(data).execute()
