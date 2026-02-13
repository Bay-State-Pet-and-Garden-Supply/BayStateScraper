"""Tests for v2 event schema with timing and metadata."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.events import (
    EventBus,
    EventEmitter,
    EventSeverity,
    EventType,
    ScraperEvent,
    create_emitter,
)


class TestScraperEventV2:
    """Test ScraperEvent class with v2 schema support."""

    def test_event_defaults_to_v1(self):
        """Events should default to version 1.0 for backward compatibility."""
        event = ScraperEvent(
            event_type=EventType.JOB_STARTED,
            job_id="test_job",
        )
        assert event.version == "1.0"

    def test_event_v2_version(self):
        """Events can be created with version 2.0."""
        event = ScraperEvent(
            event_type=EventType.STEP_STARTED,
            job_id="test_job",
            version="2.0",
        )
        assert event.version == "2.0"

    def test_v1_event_to_dict_excludes_version(self):
        """V1 events should not include version in dict output."""
        event = ScraperEvent(
            event_type=EventType.JOB_STARTED,
            job_id="test_job",
            version="1.0",
        )
        result = event.to_dict()
        assert "version" not in result

    def test_v2_event_to_dict_includes_version(self):
        """V2 events should include version in dict output."""
        event = ScraperEvent(
            event_type=EventType.STEP_STARTED,
            job_id="test_job",
            version="2.0",
        )
        result = event.to_dict()
        assert result["version"] == "2.0"

    def test_event_to_json_roundtrip(self):
        """Events should serialize and deserialize correctly."""
        event = ScraperEvent(
            event_type=EventType.STEP_COMPLETED,
            job_id="test_job",
            data={"step": {"index": 0, "action": "navigate"}},
            version="2.0",
        )
        json_str = event.to_json()
        parsed = json.loads(json_str)
        assert parsed["event_type"] == "step.completed"
        assert parsed["version"] == "2.0"
        assert parsed["data"]["step"]["index"] == 0

    def test_from_dict_with_version(self):
        """Should parse events with version field."""
        data = {
            "event_type": "step.started",
            "timestamp": datetime.now().isoformat(),
            "job_id": "test_job",
            "event_id": "evt_123",
            "severity": "info",
            "data": {},
            "version": "2.0",
        }
        event = ScraperEvent.from_dict(data)
        assert event.version == "2.0"
        assert event.event_type == EventType.STEP_STARTED

    def test_from_dict_defaults_to_v1(self):
        """Should default to v1 when version is not present."""
        data = {
            "event_type": "job.started",
            "timestamp": datetime.now().isoformat(),
            "job_id": "test_job",
            "event_id": "evt_123",
            "severity": "info",
            "data": {},
        }
        event = ScraperEvent.from_dict(data)
        assert event.version == "1.0"


class TestEventEmitterV2:
    """Test EventEmitter v2 event methods."""

    @pytest.fixture
    def event_bus(self):
        """Create a fresh EventBus for each test."""
        return EventBus(buffer_size=100, persist_path=None)

    @pytest.fixture
    def emitter(self, event_bus):
        """Create an EventEmitter with the test event bus."""
        return EventEmitter(event_bus, job_id="test_job_123")

    def test_step_started_event(self, event_bus, emitter):
        """Should emit step.started event with correct structure."""
        events: list[ScraperEvent] = []
        event_bus.subscribe(lambda e: events.append(e))

        emitter.step_started(
            scraper="test_scraper",
            step_index=0,
            action="navigate",
            name="Navigate to product page",
            sku="SKU123",
        )

        assert len(events) == 1
        event = events[0]
        assert event.event_type == EventType.STEP_STARTED
        assert event.version == "2.0"
        assert event.data["scraper"] == "test_scraper"
        assert event.data["sku"] == "SKU123"
        assert event.data["step"]["index"] == 0
        assert event.data["step"]["action"] == "navigate"
        assert event.data["step"]["name"] == "Navigate to product page"

    def test_step_completed_event_with_timing(self, event_bus, emitter):
        """Should emit step.completed event with timing metadata."""
        events: list[ScraperEvent] = []
        event_bus.subscribe(lambda e: events.append(e))

        started_at = datetime.now().isoformat()

        emitter.step_completed(
            scraper="test_scraper",
            step_index=1,
            action="extract",
            started_at=started_at,
            name="Extract product data",
            sku="SKU123",
            retry_count=0,
            max_retries=3,
        )

        assert len(events) == 1
        event = events[0]
        assert event.event_type == EventType.STEP_COMPLETED
        assert event.version == "2.0"
        assert event.data["step"]["status"] == "completed"
        assert event.data["step"]["retry_count"] == 0
        assert event.data["step"]["max_retries"] == 3
        assert "timing" in event.data
        assert event.data["timing"]["started_at"] == started_at
        assert "completed_at" in event.data["timing"]
        assert "duration_ms" in event.data["timing"]
        assert "duration_seconds" in event.data["timing"]
        assert event.data["timing"]["duration_ms"] >= 0

    def test_step_completed_with_selectors(self, event_bus, emitter):
        """Should emit step.completed with selector results."""
        events: list[ScraperEvent] = []
        event_bus.subscribe(lambda e: events.append(e))

        selectors = {
            "product_name": {"value": "h1.title", "found": True, "count": 1},
            "price": {"value": "span.price", "found": True, "count": 1, "attribute": "text"},
        }

        emitter.step_completed(
            scraper="test_scraper",
            step_index=1,
            action="extract",
            started_at=datetime.now().isoformat(),
            selectors=selectors,
        )

        event = events[0]
        assert event.data["selectors"] == selectors

    def test_step_completed_with_extraction(self, event_bus, emitter):
        """Should emit step.completed with extraction results."""
        events: list[ScraperEvent] = []
        event_bus.subscribe(lambda e: events.append(e))

        extraction = {
            "name": {"value": "Test Product", "confidence": 0.95, "status": "SUCCESS"},
            "price": {"value": "$19.99", "confidence": 0.98, "status": "SUCCESS"},
        }

        emitter.step_completed(
            scraper="test_scraper",
            step_index=1,
            action="extract",
            started_at=datetime.now().isoformat(),
            extraction=extraction,
        )

        event = events[0]
        assert event.data["extraction"] == extraction

    def test_step_failed_event(self, event_bus, emitter):
        """Should emit step.failed event with error details."""
        events: list[ScraperEvent] = []
        event_bus.subscribe(lambda e: events.append(e))

        started_at = datetime.now().isoformat()

        emitter.step_failed(
            scraper="test_scraper",
            step_index=2,
            action="click",
            started_at=started_at,
            error="Element not found",
            name="Click add to cart",
            sku="SKU123",
            retry_count=2,
            max_retries=3,
            retryable=True,
        )

        assert len(events) == 1
        event = events[0]
        assert event.event_type == EventType.STEP_FAILED
        assert event.version == "2.0"
        assert event.severity == EventSeverity.ERROR
        assert event.data["step"]["status"] == "failed"
        assert event.data["error"]["message"] == "Element not found"
        assert event.data["error"]["retryable"] is True
        assert "timing" in event.data

    def test_step_skipped_event(self, event_bus, emitter):
        """Should emit step.skipped event."""
        events: list[ScraperEvent] = []
        event_bus.subscribe(lambda e: events.append(e))

        emitter.step_skipped(
            scraper="test_scraper",
            step_index=3,
            action="login",
            reason="Already authenticated",
            name="Login step",
        )

        assert len(events) == 1
        event = events[0]
        assert event.event_type == EventType.STEP_SKIPPED
        assert event.version == "2.0"
        assert event.severity == EventSeverity.WARNING
        assert event.data["step"]["status"] == "skipped"
        assert event.data["reason"] == "Already authenticated"

    def test_selector_resolved_event_found(self, event_bus, emitter):
        """Should emit selector.resolved event when found."""
        events: list[ScraperEvent] = []
        event_bus.subscribe(lambda e: events.append(e))

        emitter.selector_resolved(
            scraper="test_scraper",
            selector_name="product_title",
            selector_value="h1.title",
            found=True,
            count=1,
            attribute="text",
            sku="SKU123",
        )

        assert len(events) == 1
        event = events[0]
        assert event.event_type == EventType.SELECTOR_RESOLVED
        assert event.version == "2.0"
        assert event.severity == EventSeverity.INFO
        assert event.data["selector"]["name"] == "product_title"
        assert event.data["selector"]["value"] == "h1.title"
        assert event.data["selector"]["found"] is True
        assert event.data["selector"]["count"] == 1
        assert event.data["selector"]["attribute"] == "text"

    def test_selector_resolved_event_not_found(self, event_bus, emitter):
        """Should emit selector.resolved event with warning when not found."""
        events: list[ScraperEvent] = []
        event_bus.subscribe(lambda e: events.append(e))

        emitter.selector_resolved(
            scraper="test_scraper",
            selector_name="out_of_stock",
            selector_value=".out-of-stock",
            found=False,
            count=0,
            error="Timeout waiting for selector",
        )

        assert len(events) == 1
        event = events[0]
        assert event.event_type == EventType.SELECTOR_RESOLVED
        assert event.severity == EventSeverity.WARNING
        assert event.data["selector"]["found"] is False
        assert event.data["selector"]["error"] == "Timeout waiting for selector"

    def test_extraction_completed_event_success(self, event_bus, emitter):
        """Should emit extraction.completed event for successful extraction."""
        events: list[ScraperEvent] = []
        event_bus.subscribe(lambda e: events.append(e))

        emitter.extraction_completed(
            scraper="test_scraper",
            field_name="price",
            value="$19.99",
            status="SUCCESS",
            confidence=0.98,
            sku="SKU123",
        )

        assert len(events) == 1
        event = events[0]
        assert event.event_type == EventType.EXTRACTION_COMPLETED
        assert event.version == "2.0"
        assert event.severity == EventSeverity.INFO
        assert event.data["extraction"]["field_name"] == "price"
        assert event.data["extraction"]["value"] == "$19.99"
        assert event.data["extraction"]["status"] == "SUCCESS"
        assert event.data["extraction"]["confidence"] == 0.98

    def test_extraction_completed_event_error(self, event_bus, emitter):
        """Should emit extraction.completed event with warning on error."""
        events: list[ScraperEvent] = []
        event_bus.subscribe(lambda e: events.append(e))

        emitter.extraction_completed(
            scraper="test_scraper",
            field_name="rating",
            value=None,
            status="NOT_FOUND",
            confidence=0.0,
            error="No rating element found",
        )

        assert len(events) == 1
        event = events[0]
        assert event.event_type == EventType.EXTRACTION_COMPLETED
        assert event.severity == EventSeverity.WARNING
        assert event.data["extraction"]["status"] == "NOT_FOUND"
        assert event.data["extraction"]["error"] == "No rating element found"


class TestV1BackwardCompatibility:
    """Test that v1 event consumers continue to work."""

    def test_v1_job_started_no_version_field(self):
        """V1 job.started events should not have version field."""
        event = ScraperEvent(
            event_type=EventType.JOB_STARTED,
            job_id="test_job",
            data={"total_skus": 10},
        )
        result = event.to_dict()
        assert "version" not in result
        assert result["event_type"] == "job.started"
        assert result["data"]["total_skus"] == 10

    def test_v1_event_json_no_version(self):
        """V1 events serialized to JSON should not contain version."""
        event = ScraperEvent(
            event_type=EventType.SKU_SUCCESS,
            job_id="test_job",
            data={"scraper": "test", "sku": "123"},
        )
        json_str = event.to_json()
        parsed = json.loads(json_str)
        assert "version" not in parsed

    def test_create_emitter_returns_v1_compatible_emitter(self):
        """create_emitter should return emitter that produces v1 compatible events by default."""
        emitter = create_emitter("test_job")

        # Emit a v1 style event
        event = emitter.job_started(
            total_skus=10,
            scrapers=["scraper1", "scraper2"],
        )

        result = event.to_dict()
        assert "version" not in result
        assert result["event_type"] == "job.started"


class TestEventBusV2:
    """Test EventBus with v2 events."""

    def test_event_bus_buffers_v2_events(self):
        """EventBus should buffer v2 events correctly."""
        bus = EventBus(buffer_size=50)

        # Emit v2 events
        for i in range(5):
            event = ScraperEvent(
                event_type=EventType.STEP_COMPLETED,
                job_id="test_job",
                version="2.0",
                data={"step": {"index": i}},
            )
            bus.emit(event)

        events = bus.get_events(job_id="test_job")
        assert len(events) == 5
        for event in events:
            assert event.version == "2.0"

    def test_get_events_as_dicts_includes_v2_fields(self):
        """get_events_as_dicts should include v2 fields like version."""
        bus = EventBus(buffer_size=50)

        event = ScraperEvent(
            event_type=EventType.STEP_STARTED,
            job_id="test_job",
            version="2.0",
            data={"step": {"index": 0, "action": "navigate"}},
        )
        bus.emit(event)

        dicts = bus.get_events_as_dicts(job_id="test_job")
        assert len(dicts) == 1
        assert dicts[0]["version"] == "2.0"


class TestEventTimingCalculation:
    """Test timing calculation in v2 events."""

    @pytest.fixture
    def event_bus(self):
        """Create a fresh EventBus for each test."""
        return EventBus(buffer_size=50, persist_path=None)

    def test_duration_calculation(self, event_bus):
        """Should correctly calculate duration from started_at to completed_at."""
        emitter = EventEmitter(event_bus, job_id="test_job")
        events: list[ScraperEvent] = []
        event_bus.subscribe(lambda e: events.append(e))

        # Use a known start time
        started_at = "2025-02-12T10:30:00.000"

        # Emit completion
        emitter.step_completed(
            scraper="test",
            step_index=0,
            action="navigate",
            started_at=started_at,
        )

        event = events[0]
        timing = event.data["timing"]

        # Verify timing structure
        assert timing["started_at"] == started_at
        assert "completed_at" in timing
        assert "duration_ms" in timing
        assert "duration_seconds" in timing

        # Verify duration calculation (should be non-negative)
        assert timing["duration_ms"] >= 0
        assert timing["duration_seconds"] >= 0
        # duration_seconds should be duration_ms / 1000
        assert abs(timing["duration_seconds"] - timing["duration_ms"] / 1000) < 0.01


class TestStepExecutorEvents:
    """Test StepExecutor v2 event emission integration."""

    @pytest.fixture
    def mock_browser(self):
        """Create a mock browser."""
        return MagicMock()

    @pytest.fixture
    def mock_retry_executor(self):
        """Create a mock retry executor."""
        executor = MagicMock()
        executor.execute_with_retry = MagicMock()
        return executor

    @pytest.fixture
    def event_bus(self):
        """Create a fresh EventBus."""
        return EventBus(buffer_size=100, persist_path=None)

    @pytest.fixture
    def event_emitter(self, event_bus):
        """Create an EventEmitter."""
        return EventEmitter(event_bus, job_id="test_job")

    def test_step_executor_tracks_events(self, mock_browser, mock_retry_executor, event_bus, event_emitter):
        """StepExecutor should track events for v2 emission."""
        from scrapers.executor.step_executor import StepExecutor

        step_executor = StepExecutor(
            config_name="test_scraper",
            browser=mock_browser,
            retry_executor=mock_retry_executor,
            enable_retry=False,
            event_emitter=event_emitter,
        )

        # Verify the executor has event_emitter
        assert step_executor.event_emitter == event_emitter

    def test_track_selector_result(self, mock_browser, mock_retry_executor, event_bus, event_emitter):
        """StepExecutor should track selector results for v2 events."""
        from scrapers.executor.step_executor import StepExecutor

        events: list[ScraperEvent] = []
        event_bus.subscribe(lambda e: events.append(e))

        step_executor = StepExecutor(
            config_name="test_scraper",
            browser=mock_browser,
            retry_executor=mock_retry_executor,
            event_emitter=event_emitter,
        )

        # Track a selector result
        step_executor.track_selector_result(
            name="product_name",
            selector="h1.title",
            found=True,
            count=1,
            attribute="text",
        )

        # Should have emitted selector.resolved event
        assert len(events) == 1
        assert events[0].event_type == EventType.SELECTOR_RESOLVED
        assert events[0].data["selector"]["name"] == "product_name"
        assert events[0].data["selector"]["found"] is True

        # Should be tracked internally
        assert "product_name" in step_executor._step_selector_results

    def test_track_extraction_result(self, mock_browser, mock_retry_executor, event_bus, event_emitter):
        """StepExecutor should track extraction results for v2 events."""
        from scrapers.executor.step_executor import StepExecutor

        events: list[ScraperEvent] = []
        event_bus.subscribe(lambda e: events.append(e))

        step_executor = StepExecutor(
            config_name="test_scraper",
            browser=mock_browser,
            retry_executor=mock_retry_executor,
            event_emitter=event_emitter,
        )

        # Track an extraction result
        step_executor.track_extraction_result(
            field_name="price",
            value="$19.99",
            status="SUCCESS",
            confidence=0.95,
        )

        # Should have emitted extraction.completed event
        assert len(events) == 1
        assert events[0].event_type == EventType.EXTRACTION_COMPLETED
        assert events[0].data["extraction"]["field_name"] == "price"
        assert events[0].data["extraction"]["value"] == "$19.99"

        # Should be tracked internally
        assert "price" in step_executor._step_extraction_results


class TestEventSchemaCompliance:
    """Test compliance with event-schema-v2.json."""

    @pytest.fixture
    def event_bus(self):
        """Create a fresh EventBus for each test."""
        return EventBus(buffer_size=50, persist_path=None)

    def test_step_completed_has_required_fields(self, event_bus):
        """step.completed should have all required fields per schema."""
        emitter = EventEmitter(event_bus, job_id="test_job")

        event = emitter.step_completed(
            scraper="test_scraper",
            step_index=0,
            action="navigate",
            started_at=datetime.now().isoformat(),
            name="Test step",
        )

        # Required fields per schema: step.index, step.action, step.status, timing.duration_ms
        assert "step" in event.data
        assert event.data["step"]["index"] == 0
        assert event.data["step"]["action"] == "navigate"
        assert event.data["step"]["status"] == "completed"
        assert "timing" in event.data
        assert "duration_ms" in event.data["timing"]

    def test_selector_resolved_has_required_fields(self, event_bus):
        """selector.resolved should have all required fields per schema."""
        emitter = EventEmitter(event_bus, job_id="test_job")

        event = emitter.selector_resolved(
            scraper="test_scraper",
            selector_name="product_title",
            selector_value="h1.title",
            found=True,
            count=1,
        )

        # Required fields per schema: selector.name, selector.found
        assert "selector" in event.data
        assert event.data["selector"]["name"] == "product_title"
        assert event.data["selector"]["found"] is True

    def test_extraction_completed_has_required_fields(self, event_bus):
        """extraction.completed should have all required fields per schema."""
        emitter = EventEmitter(event_bus, job_id="test_job")

        event = emitter.extraction_completed(
            scraper="test_scraper",
            field_name="price",
            value="$19.99",
            status="SUCCESS",
        )

        # Required fields per schema: extraction.field_name, extraction.status
        assert "extraction" in event.data
        assert event.data["extraction"]["field_name"] == "price"
        assert event.data["extraction"]["status"] == "SUCCESS"

    def test_step_started_has_required_fields(self, event_bus):
        """step.started should have all required fields per schema."""
        emitter = EventEmitter(event_bus, job_id="test_job")

        event = emitter.step_started(
            scraper="test_scraper",
            step_index=0,
            action="navigate",
        )

        # Required fields per schema: step.index, step.action
        assert "step" in event.data
        assert event.data["step"]["index"] == 0
        assert event.data["step"]["action"] == "navigate"
