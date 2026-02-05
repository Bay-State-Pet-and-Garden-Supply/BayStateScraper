"""
Extraction Result Handler

Handles extraction result events and persists them to the database.
"""

from __future__ import annotations

from typing import Any, Protocol

from scrapers.events.extraction import ExtractionResultEvent


class SupabaseClient(Protocol):
    """Protocol for Supabase client."""

    def table(self, name: str) -> Any: ...


class ExtractionResultHandler:
    """Handler for extraction result events."""

    def __init__(self, supabase: SupabaseClient) -> None:
        """Initialize handler with Supabase client."""
        self.supabase = supabase

    def handle(self, event: ExtractionResultEvent) -> None:
        """Persist extraction result event to database."""
        data = {
            "test_run_id": getattr(event, "test_run_id", None),
            "scraper_id": getattr(event, "scraper_id", None),
            "scraper": event.scraper,
            "sku": event.sku,
            "field_name": event.field_name,
            "field_value": event.field_value,
            "status": event.status,
            "duration_ms": event.duration_ms,
            "error_message": event.error_message,
        }

        self.supabase.table("scraper_extraction_results").insert(data).execute()
