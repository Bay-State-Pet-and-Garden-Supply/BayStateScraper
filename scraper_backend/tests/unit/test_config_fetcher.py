"""
Tests for config fetcher - fetch latest published config and validation.
"""

from unittest.mock import MagicMock, patch

import pytest

from scraper_backend.core.config_fetcher import (
    fetch_published_config,
    validate_config,
    fetch_and_validate_config,
    ConfigFetchError,
    ConfigValidationError,
    PublishedConfig,
)


class TestPublishedConfig:
    """Tests for PublishedConfig dataclass."""

    def test_published_config_creation(self):
        """Test creating a PublishedConfig with valid data."""
        config = PublishedConfig(
            schema_version="1.0",
            slug="test-scraper",
            version_number=1,
            status="published",
            config={"name": "test", "base_url": "https://example.com"},
            published_at="2026-01-22T10:00:00Z",
            published_by="user-123",
        )

        assert config.schema_version == "1.0"
        assert config.slug == "test-scraper"
        assert config.version_number == 1
        assert config.status == "published"
        assert config.config["name"] == "test"
        assert config.published_by == "user-123"


class TestConfigFetchError:
    """Tests for ConfigFetchError exception."""

    def test_error_with_all_fields(self):
        """Test ConfigFetchError with all fields."""
        error = ConfigFetchError(
            message="Failed to fetch config",
            config_slug="test-scraper",
            schema_version="1.0",
        )

        assert "Failed to fetch config" in str(error)
        assert error.config_slug == "test-scraper"
        assert error.schema_version == "1.0"

    def test_error_with_minimal_fields(self):
        """Test ConfigFetchError with minimal fields."""
        error = ConfigFetchError(message="Something went wrong")

        assert "Something went wrong" in str(error)
        assert error.config_slug is None
        assert error.schema_version is None


class TestConfigValidationError:
    """Tests for ConfigValidationError exception."""

    def test_error_with_validation_details(self):
        """Test ConfigValidationError with validation errors."""
        validation_errors = [
            {"loc": ("base_url",), "msg": "field required", "type": "missing"},
            {"loc": ("name",), "msg": "field required", "type": "missing"},
        ]

        error = ConfigValidationError(
            message="Config validation failed",
            config_slug="test-scraper",
            schema_version="1.0",
            validation_errors=validation_errors,
        )

        assert "test-scraper" in str(error)
        assert "1.0" in str(error)
        assert len(error.validation_errors) == 2


class TestFetchPublishedConfig:
    """Tests for fetch_published_config function."""

    def test_fetch_success(self, mock_api_client):
        """Test successful config fetch."""
        mock_api_client._make_request.return_value = {
            "schema_version": "1.0",
            "slug": "hobby-lobby",
            "version_number": 2,
            "status": "published",
            "config": {
                "name": "hobby-lobby",
                "base_url": "https://www.hobbylobby.com",
                "selectors": [],
                "workflows": [],
            },
            "published_at": "2026-01-22T10:00:00Z",
            "published_by": "user-123",
        }

        result = fetch_published_config(mock_api_client, "hobby-lobby")

        assert result.slug == "hobby-lobby"
        assert result.schema_version == "1.0"
        assert result.version_number == 2
        assert result.status == "published"
        assert result.config["name"] == "hobby-lobby"

    def test_fetch_missing_key_raises_config_fetch_error(self, mock_api_client):
        """Test that missing key in response raises ConfigFetchError."""
        mock_api_client._make_request.return_value = {
            "slug": "test-scraper",
            # Missing schema_version and other required keys
        }

        with pytest.raises(ConfigFetchError) as exc_info:
            fetch_published_config(mock_api_client, "test-scraper")

        assert "Invalid response format" in str(exc_info.value)
        assert "test-scraper" in str(exc_info.value)

    def test_fetch_api_error_raises_config_fetch_error(self, mock_api_client):
        """Test that API errors are wrapped in ConfigFetchError."""
        mock_api_client._make_request.side_effect = Exception("Connection refused")

        with pytest.raises(ConfigFetchError) as exc_info:
            fetch_published_config(mock_api_client, "test-scraper")

        assert "Failed to fetch config" in str(exc_info.value)
        assert "test-scraper" in str(exc_info.value)
        assert exc_info.value.original_error is not None

    @pytest.fixture
    def mock_api_client(self):
        """Create a mock API client."""
        mock = MagicMock()
        mock._make_request = MagicMock()
        return mock


class TestValidateConfig:
    """Tests for validate_config function."""

    def test_valid_config_passes_validation(self, valid_config_dict):
        """Test that a valid config passes validation."""
        published_config = PublishedConfig(
            schema_version="1.0",
            slug="test-scraper",
            version_number=1,
            status="published",
            config=valid_config_dict,
            published_at="2026-01-22T10:00:00Z",
            published_by="user-123",
        )

        result = validate_config(published_config)

        assert result.name == "test-scraper"
        assert result.base_url == "https://example.com"
        assert result.schema_version == "1.0"

    def test_invalid_config_raises_validation_error(self, invalid_config_dict):
        """Test that an invalid config raises ConfigValidationError."""
        published_config = PublishedConfig(
            schema_version="1.0",
            slug="test-scraper",
            version_number=1,
            status="published",
            config=invalid_config_dict,
            published_at="2026-01-22T10:00:00Z",
            published_by="user-123",
        )

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_config(published_config)

        assert "test-scraper" in str(exc_info.value)
        assert "1.0" in str(exc_info.value)
        assert len(exc_info.value.validation_errors) > 0

    def test_unknown_schema_version_fails_validation(self):
        """Test that unknown schema_version is rejected."""
        config_dict = {
            "schema_version": "99.0",  # Unknown version
            "name": "test",
            "base_url": "https://example.com",
            "selectors": [],
            "workflows": [],
        }

        published_config = PublishedConfig(
            schema_version="99.0",
            slug="test-scraper",
            version_number=1,
            status="published",
            config=config_dict,
            published_at="2026-01-22T10:00:00Z",
            published_by="user-123",
        )

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_config(published_config)

        assert (
            "schema_version" in str(exc_info.value).lower()
            or "unknown" in str(exc_info.value).lower()
        )

    @pytest.fixture
    def valid_config_dict(self):
        """Return a valid minimal config dictionary."""
        return {
            "schema_version": "1.0",
            "name": "test-scraper",
            "base_url": "https://example.com",
            "selectors": [],
            "workflows": [],
        }

    @pytest.fixture
    def invalid_config_dict(self):
        """Return an invalid config dictionary (missing required fields)."""
        return {
            "schema_version": "1.0",
            # Missing "name" and "base_url"
            "selectors": [],
            "workflows": [],
        }


class TestFetchAndValidateConfig:
    """Tests for fetch_and_validate_config combined function."""

    def test_fetch_and_validate_success(self, mock_api_client, valid_config_dict):
        """Test successful fetch and validate."""
        mock_api_client._make_request.return_value = {
            "schema_version": "1.0",
            "slug": "test-scraper",
            "version_number": 1,
            "status": "published",
            "config": valid_config_dict,
            "published_at": "2026-01-22T10:00:00Z",
            "published_by": "user-123",
        }

        published, validated = fetch_and_validate_config(
            mock_api_client, "test-scraper"
        )

        assert published.slug == "test-scraper"
        assert validated.name == "test-scraper"

    def test_fetch_failure_raises_config_fetch_error(self, mock_api_client):
        """Test that fetch errors raise ConfigFetchError."""
        mock_api_client._make_request.side_effect = Exception("API unavailable")

        with pytest.raises(ConfigFetchError):
            fetch_and_validate_config(mock_api_client, "test-scraper")

    def test_validation_failure_raises_config_validation_error(
        self, mock_api_client, invalid_config_dict
    ):
        """Test that validation errors raise ConfigValidationError."""
        mock_api_client._make_request.return_value = {
            "schema_version": "1.0",
            "slug": "test-scraper",
            "version_number": 1,
            "status": "published",
            "config": invalid_config_dict,
            "published_at": "2026-01-22T10:00:00Z",
            "published_by": "user-123",
        }

        with pytest.raises(ConfigValidationError):
            fetch_and_validate_config(mock_api_client, "test-scraper")

    @pytest.fixture
    def mock_api_client(self):
        """Create a mock API client."""
        mock = MagicMock()
        mock._make_request = MagicMock()
        return mock

    @pytest.fixture
    def valid_config_dict(self):
        """Return a valid minimal config dictionary."""
        return {
            "schema_version": "1.0",
            "name": "test-scraper",
            "base_url": "https://example.com",
            "selectors": [],
            "workflows": [],
        }

    @pytest.fixture
    def invalid_config_dict(self):
        """Return an invalid config dictionary."""
        return {
            "schema_version": "1.0",
            # Missing required fields
        }


class TestFailFastBehavior:
    """Tests specifically for fail-fast behavior requirements."""

    def test_validation_error_before_expensive_operations(
        self, mock_api_client, invalid_config_dict
    ):
        """Verify validation fails fast without expensive operations."""
        mock_api_client._make_request.return_value = {
            "schema_version": "1.0",
            "slug": "test-scraper",
            "version_number": 1,
            "status": "published",
            "config": invalid_config_dict,
            "published_at": "2026-01-22T10:00:00Z",
            "published_by": "user-123",
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            fetch_and_validate_config(mock_api_client, "test-scraper")

        # Verify the API was called but no browser/expensive ops were started
        mock_api_client._make_request.assert_called_once()
        assert "test-scraper" == exc_info.value.config_slug

    def test_clear_error_message_includes_slug_and_version(
        self, mock_api_client, invalid_config_dict
    ):
        """Verify error messages include config slug and schema_version."""
        mock_api_client._make_request.return_value = {
            "schema_version": "1.0",
            "slug": "my-scraper",
            "version_number": 5,
            "status": "published",
            "config": invalid_config_dict,
            "published_at": "2026-01-22T10:00:00Z",
            "published_by": "user-123",
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            fetch_and_validate_config(mock_api_client, "my-scraper")

        error_message = str(exc_info.value)
        assert "my-scraper" in error_message
        assert "1.0" in error_message

    @pytest.fixture
    def mock_api_client(self):
        """Create a mock API client."""
        mock = MagicMock()
        mock._make_request = MagicMock()
        return mock

    @pytest.fixture
    def invalid_config_dict(self):
        """Return an invalid config dictionary."""
        return {
            "schema_version": "1.0",
            # Missing required fields
        }
