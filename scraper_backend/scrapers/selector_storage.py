"""
Selector Storage System for Static CSS Selectors

This module provides a JSON-based storage system for learned CSS selectors
used in web scraping. It includes confidence scoring, fallback chains, and
automatic learning capabilities.
"""
from __future__ import annotations


import json
import logging
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SelectorData:
    """Data structure for a single selector entry."""

    def __init__(
        self,
        selector: str,
        confidence: float = 0.5,
        last_updated: str | None = None,
        fallbacks: list[str] | None = None,
    ) -> None:
        self.selector = selector
        self.confidence = confidence
        self.last_updated = last_updated or datetime.now(UTC).isoformat()
        self.fallbacks = fallbacks or []

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "selector": self.selector,
            "confidence": self.confidence,
            "last_updated": self.last_updated,
            "fallbacks": self.fallbacks,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SelectorData":
        """Create from dictionary."""
        return cls(
            selector=data["selector"],
            confidence=data.get("confidence", 0.5),
            last_updated=data.get("last_updated"),
            fallbacks=data.get("fallbacks", []),
        )

    def update_confidence(self, success: bool, learning_rate: float = 0.1):
        """Update confidence based on extraction success/failure."""
        if success:
            # Increase confidence towards 1.0
            self.confidence = min(1.0, self.confidence + learning_rate)
        else:
            # Decrease confidence towards 0.0
            self.confidence = max(0.0, self.confidence - learning_rate)

        self.last_updated = datetime.now(UTC).isoformat()


class SelectorStorage:
    """JSON-based storage for CSS selectors with confidence scoring."""

    def __init__(self, storage_path: str = "data/selectors.json") -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, dict[str, SelectorData]] = {}
        self.metadata = {
            "version": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
            "last_modified": datetime.now(UTC).isoformat(),
        }
        self.load()

    def load(self):
        """Load selector data from JSON file."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, encoding="utf-8") as f:
                    raw_data = json.load(f)

                self.metadata = raw_data.get("metadata", self.metadata)
                selectors_data = raw_data.get("selectors", {})

                self.data = {}
                for domain, fields in selectors_data.items():
                    self.data[domain] = {}
                    for field_name, field_data in fields.items():
                        self.data[domain][field_name] = SelectorData.from_dict(field_data)

            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Error loading selector storage: {e}. Starting fresh.")
                self.data = {}
        else:
            self.data = {}

    def save(self):
        """Save selector data to JSON file."""
        self.metadata["last_modified"] = datetime.now(UTC).isoformat()

        selectors_dict: dict[str, dict[str, Any]] = {}
        for domain, fields in self.data.items():
            selectors_dict[domain] = {}
            for field_name, selector_data in fields.items():
                selectors_dict[domain][field_name] = selector_data.to_dict()

        data_to_save = {"metadata": self.metadata, "selectors": selectors_dict}

        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=2, ensure_ascii=False)

    def get_selector(self, domain: str, field_name: str) -> SelectorData | None:
        """Get selector data for a specific domain and field."""
        return self.data.get(domain, {}).get(field_name)

    def set_selector(
        self,
        domain: str,
        field_name: str,
        selector: str,
        confidence: float = 0.5,
        fallbacks: list[str] | None = None,
    ):
        """Set or update a selector for a domain and field."""
        if domain not in self.data:
            self.data[domain] = {}

        self.data[domain][field_name] = SelectorData(
            selector=selector, confidence=confidence, fallbacks=fallbacks
        )
        self.save()

    def update_selector_confidence(self, domain: str, field_name: str, success: bool):
        """Update confidence score for a selector based on extraction result."""
        selector_data = self.get_selector(domain, field_name)
        if selector_data:
            selector_data.update_confidence(success)
            self.save()

    def get_fallback_chain(self, domain: str, field_name: str) -> list[str]:
        """Get the complete fallback chain for a selector (primary + fallbacks)."""
        selector_data = self.get_selector(domain, field_name)
        if not selector_data:
            return []

        chain = [selector_data.selector]
        chain.extend(selector_data.fallbacks)
        return chain

    def add_fallback(self, domain: str, field_name: str, fallback_selector: str):
        """Add a fallback selector to an existing selector."""
        selector_data = self.get_selector(domain, field_name)
        if selector_data and fallback_selector not in selector_data.fallbacks:
            selector_data.fallbacks.append(fallback_selector)
            selector_data.last_updated = datetime.now(UTC).isoformat()
            self.save()

    def get_all_domains(self) -> list[str]:
        """Get list of all stored domains."""
        return list(self.data.keys())

    def get_domain_fields(self, domain: str) -> list[str]:
        """Get list of all fields for a domain."""
        return list(self.data.get(domain, {}).keys())

    def remove_selector(self, domain: str, field_name: str):
        """Remove a selector for a domain and field."""
        if domain in self.data and field_name in self.data[domain]:
            del self.data[domain][field_name]
            if not self.data[domain]:
                del self.data[domain]
            self.save()

    def clear_domain(self, domain: str):
        """Clear all selectors for a domain."""
        if domain in self.data:
            del self.data[domain]
            self.save()


class SelectorManager:
    """High-level manager for selector learning, retrieval, and validation."""

    def __init__(self, storage_path: str = "data/selectors.json") -> None:
        self.storage = SelectorStorage(storage_path)

    def learn_selector(
        self,
        domain: str,
        field_name: str,
        selector: str,
        success: bool = True,
        initial_confidence: float = 0.5,
    ):
        """Learn or update a selector with confidence adjustment."""
        existing = self.storage.get_selector(domain, field_name)

        if existing:
            # Update existing selector
            if selector != existing.selector:
                # New selector, add as fallback and promote if more successful
                if success and existing.confidence < 0.8:
                    # Promote new selector to primary
                    existing.fallbacks.insert(0, existing.selector)
                    existing.selector = selector
                    existing.confidence = initial_confidence
                else:
                    # Add as fallback
                    self.storage.add_fallback(domain, field_name, selector)
            else:
                # Same selector, update confidence
                self.storage.update_selector_confidence(domain, field_name, success)
        else:
            # New selector
            self.storage.set_selector(domain, field_name, selector, initial_confidence)

    def get_best_selector(self, domain: str, field_name: str) -> str | None:
        """Get the best (highest confidence) selector for a field."""
        selector_data = self.storage.get_selector(domain, field_name)
        return selector_data.selector if selector_data else None

    def get_selector_with_fallbacks(self, domain: str, field_name: str) -> list[str]:
        """Get primary selector and all fallbacks."""
        return self.storage.get_fallback_chain(domain, field_name)

    def validate_selector_exists(self, domain: str, field_name: str) -> bool:
        """Check if a selector exists for the given domain and field."""
        return self.storage.get_selector(domain, field_name) is not None

    def get_selector_stats(self, domain: str, field_name: str) -> dict[str, Any] | None:
        """Get statistics for a selector."""
        selector_data = self.storage.get_selector(domain, field_name)
        if not selector_data:
            return None

        return {
            "selector": selector_data.selector,
            "confidence": selector_data.confidence,
            "last_updated": selector_data.last_updated,
            "fallback_count": len(selector_data.fallbacks),
            "total_selectors": len(selector_data.fallbacks) + 1,
        }

    def cleanup_low_confidence_selectors(self, threshold: float = 0.2):
        """Remove selectors with confidence below threshold."""
        domains_to_remove: list[str] = []

        for domain, fields in self.storage.data.items():
            fields_to_remove: list[str] = []

            for field_name, selector_data in fields.items():
                if selector_data.confidence < threshold:
                    fields_to_remove.append(field_name)

            for field_name in fields_to_remove:
                del fields[field_name]

            if not fields:
                domains_to_remove.append(domain)

        for domain in domains_to_remove:
            del self.storage.data[domain]

        if domains_to_remove:
            self.storage.save()
