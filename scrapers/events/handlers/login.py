"""
Login Result Handler

Handles login status events and persists them to the database.
"""

from __future__ import annotations

from typing import Any, Protocol

from scrapers.events.login import LoginStatusEvent


class SupabaseClient(Protocol):
    """Protocol for Supabase client."""

    def table(self, name: str) -> Any: ...


class LoginResultHandler:
    """Handler for login status events."""

    def __init__(self, supabase: SupabaseClient) -> None:
        """Initialize handler with Supabase client."""
        self.supabase = supabase

    def handle(self, event: LoginStatusEvent) -> None:
        """Persist login status event to database."""
        data = {
            "test_run_id": getattr(event, "test_run_id", None),
            "scraper_id": getattr(event, "scraper_id", None),
            "scraper": event.scraper,
            "sku": event.sku,
            "username_field_status": event.username_field_status,
            "password_field_status": event.password_field_status,
            "submit_button_status": event.submit_button_status,
            "success_indicator_status": event.success_indicator_status,
            "overall_status": event.status,
            "duration_ms": event.duration_ms,
            "error_message": event.error_message,
        }

        self.supabase.table("scraper_login_results").insert(data).execute()
