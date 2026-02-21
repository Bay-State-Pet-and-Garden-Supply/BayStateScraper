"""Tests for runner configuration error handling."""

from unittest.mock import MagicMock, patch

import pytest

from core.api_client import JobConfig, ScraperConfig
from runner import run_job, ConfigurationError


class TestRunnerConfigurationErrorHandling:
    """Test suite for runner configuration error handling."""

    def test_config_parsing_error_is_raised(self):
        """Test that ConfigurationError is raised when scraper config parsing fails."""
        # Create a mock job config with an invalid scraper config
        # Using invalid selectors (missing required 'selector' field) will cause parsing to fail
        scraper_configs = [
            ScraperConfig(
                name="valid-scraper",
                base_url="https://example.com",
                search_url_template="https://example.com/search?q={sku}",
                selectors=[],  # Valid: empty list
                options={},
                test_skus=[],
            ),
            ScraperConfig(
                name="invalid-scraper",
                base_url="https://example.com",
                search_url_template="https://example.com/search?q={sku}",
                selectors=[{"name": "bad_selector"}],  # Invalid: missing 'selector' field
                options={},
                test_skus=[],
            ),
        ]

        job_config = JobConfig(
            job_id="test-job-123",
            skus=["SKU001", "SKU002"],
            scrapers=scraper_configs,
            test_mode=False,
            max_workers=1,
        )

        # The run_job function should raise ConfigurationError
        with pytest.raises(ConfigurationError) as exc_info:
            run_job(job_config, runner_name="test-runner")

        # Verify error message mentions the failed scraper
        error_message = str(exc_info.value)
        assert "invalid-scraper" in error_message
        assert "1 scraper(s)" in error_message

    def test_multiple_config_errors_are_reported(self):
        """Test that multiple config failures are all reported."""
        scraper_configs = [
            ScraperConfig(
                name="scraper-1",
                base_url="https://example.com",
                search_url_template="https://example.com/search?q={sku}",
                selectors=[{"name": "bad_selector1"}],  # Invalid: missing 'selector' field
                options={},
                test_skus=[],
            ),
            ScraperConfig(
                name="scraper-2",
                base_url="https://example.com",
                search_url_template="https://example.com/search?q={sku}",
                selectors=[{"name": "bad_selector2"}],  # Invalid: missing 'selector' field
                options={},
                test_skus=[],
            ),
        ]

        job_config = JobConfig(
            job_id="test-job-456",
            skus=["SKU001"],
            scrapers=scraper_configs,
            test_mode=False,
            max_workers=1,
        )

        with pytest.raises(ConfigurationError) as exc_info:
            run_job(job_config, runner_name="test-runner")

        error_message = str(exc_info.value)
        assert "scraper-1" in error_message
        assert "scraper-2" in error_message
        assert "2 scraper(s)" in error_message

    def test_no_configs_raises_error(self):
        """Test that ConfigurationError is raised when no valid configs exist."""
        # Create an empty scraper config list
        job_config = JobConfig(
            job_id="test-job-789",
            skus=["SKU001"],
            scrapers=[],  # Empty scrapers list
            test_mode=False,
            max_workers=1,
        )

        with pytest.raises(ConfigurationError) as exc_info:
            run_job(job_config, runner_name="test-runner")

        error_message = str(exc_info.value)
        assert "No scrapers specified in job configuration" in error_message

    def test_valid_configs_succeed(self):
        """Test that valid configurations are processed successfully."""
        # Create a mock emitter that doesn't actually emit
        from core.events import EventEmitter

        mock_emitter = MagicMock(spec=EventEmitter)

        # Patch the event emitter creation
        import runner

        original_create_emitter = runner.create_emitter

        try:
            runner.create_emitter = lambda job_id: mock_emitter

            # Create a minimal valid config
            scraper_configs = [
                ScraperConfig(
                    name="test-scraper",
                    base_url="https://example.com",
                    search_url_template="https://example.com/search?q={sku}",
                    selectors=[],  # Valid: empty list
                    options={},
                    test_skus=[],
                ),
            ]

            job_config = JobConfig(
                job_id="test-job-valid",
                skus=["SKU001"],
                scrapers=scraper_configs,
                test_mode=True,
                max_workers=1,
            )

            # This should not raise an error
            results = run_job(job_config, runner_name="test-runner")

            # Verify the function returned without error
            assert results is not None
            assert "scrapers_run" in results
            assert "test-scraper" in results["scrapers_run"]
        finally:
            # Restore the original function
            runner.create_emitter = original_create_emitter


def test_discovery_job_uses_per_sku_context_items() -> None:
    scraper_configs = [
        ScraperConfig(
            name="ai_discovery",
            base_url="https://example.com",
            selectors=[],
            options={},
            test_skus=[],
        )
    ]

    job_config = JobConfig(
        job_id="discovery-job-ctx",
        skus=["SKU_A", "SKU_B"],
        scrapers=scraper_configs,
        test_mode=False,
        max_workers=1,
        job_type="discovery",
        job_config={
            "items": [
                {
                    "sku": "SKU_A",
                    "product_name": "Alpha Toy",
                    "brand": "Brand A",
                    "category": "Dog Toys",
                },
                {
                    "sku": "SKU_B",
                    "product_name": "Beta Toy",
                    "brand": "Brand B",
                    "category": "Dog Toys",
                },
            ]
        },
    )

    captured_items: list[dict[str, object]] = []

    class StubDiscoveryScraper:
        def __init__(self, **kwargs):
            _ = kwargs

        async def scrape_products_batch(self, items, max_concurrency=1):
            captured_items.extend(items)
            _ = max_concurrency
            return [
                MagicMock(
                    sku=item["sku"],
                    success=False,
                    error="stub",
                    cost_usd=0.0,
                    size_metrics=None,
                    product_name=None,
                    description=None,
                    images=[],
                    categories=[],
                    url=None,
                    source_website=None,
                    confidence=0.0,
                )
                for item in items
            ]

    with patch("runner.AIDiscoveryScraper", StubDiscoveryScraper):
        run_job(job_config, runner_name="test-runner")

    assert len(captured_items) == 2
    assert captured_items[0]["sku"] == "SKU_A"
    assert captured_items[0]["product_name"] == "Alpha Toy"
    assert captured_items[0]["brand"] == "Brand A"
    assert captured_items[1]["sku"] == "SKU_B"
    assert captured_items[1]["product_name"] == "Beta Toy"
    assert captured_items[1]["brand"] == "Brand B"


def test_empty_object_selectors_payload_does_not_fail_parsing() -> None:
    scraper_configs = [
        ScraperConfig(
            name="bradley",
            base_url="https://example.com",
            search_url_template="https://example.com/search?q={sku}",
            selectors={},
            options={},
            test_skus=[],
        )
    ]

    job_config = JobConfig(
        job_id="test-job-empty-selectors-dict",
        skus=["SKU001"],
        scrapers=scraper_configs,
        test_mode=False,
        max_workers=1,
    )

    class StubWorkflowExecutor:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs
            self.browser = None

        async def initialize(self):
            return None

        async def execute_workflow(self, context=None, quit_browser=False):
            _ = context, quit_browser
            return {"success": False, "results": {}}

    with patch("runner.WorkflowExecutor", StubWorkflowExecutor):
        results = run_job(job_config, runner_name="test-runner")

    assert results is not None
    assert "bradley" in results["scrapers_run"]
