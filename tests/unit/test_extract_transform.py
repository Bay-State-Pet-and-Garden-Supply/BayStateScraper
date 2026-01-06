"""Unit tests for the extract_and_transform action."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


class TestExtractAndTransformAction:
    """Tests for ExtractAndTransformAction."""

    @pytest.fixture
    def mock_executor(self):
        """Create a mock WorkflowExecutor."""
        executor = MagicMock()
        executor.results = {}
        return executor

    @pytest.fixture
    def action(self, mock_executor):
        """Create action instance with mock executor."""
        from scrapers.actions.handlers.extract_transform import (
            ExtractAndTransformAction,
        )

        return ExtractAndTransformAction(mock_executor)

    def test_extract_single_field_no_transform(self, action, mock_executor):
        """Test extracting a single field without transformation."""
        mock_element = MagicMock()
        mock_executor.find_element_safe.return_value = mock_element
        mock_executor._extract_value_from_element.return_value = "Test Product Name"

        action.execute({"fields": [{"name": "Name", "selector": "#productTitle"}]})

        assert mock_executor.results["Name"] == "Test Product Name"
        mock_executor.find_element_safe.assert_called_once_with("#productTitle")

    def test_extract_with_regex_transform(self, action, mock_executor):
        """Test extracting with regex transformation."""
        mock_element = MagicMock()
        mock_executor.find_element_safe.return_value = mock_element
        mock_executor._extract_value_from_element.return_value = (
            "Visit the Acme Brand Store"
        )

        action.execute(
            {
                "fields": [
                    {
                        "name": "Brand",
                        "selector": "#bylineInfo",
                        "transform": [
                            {
                                "type": "regex_extract",
                                "pattern": "Visit the (.+) Store",
                                "group": 1,
                            }
                        ],
                    }
                ]
            }
        )

        assert mock_executor.results["Brand"] == "Acme Brand"

    def test_extract_multiple_with_replace_transform(self, action, mock_executor):
        """Test extracting multiple values with replace transformation."""
        mock_elements = [MagicMock(), MagicMock(), MagicMock()]
        mock_executor.find_elements_safe.return_value = mock_elements
        mock_executor._extract_value_from_element.side_effect = [
            "image1_AC_US40_.jpg",
            "image2_AC_US40_.jpg",
            "image3_AC_US40_.jpg",
        ]

        action.execute(
            {
                "fields": [
                    {
                        "name": "Images",
                        "selector": "#altImages img",
                        "attribute": "src",
                        "multiple": True,
                        "transform": [
                            {
                                "type": "replace",
                                "pattern": "_AC_US40_",
                                "replacement": "_AC_SL1500_",
                            }
                        ],
                    }
                ]
            }
        )

        assert mock_executor.results["Images"] == [
            "image1_AC_SL1500_.jpg",
            "image2_AC_SL1500_.jpg",
            "image3_AC_SL1500_.jpg",
        ]

    def test_extract_optional_field_not_found(self, action, mock_executor):
        """Test that optional fields don't fail when not found."""
        mock_executor.find_element_safe.return_value = None

        action.execute(
            {"fields": [{"name": "Weight", "selector": ".weight", "required": False}]}
        )

        assert mock_executor.results["Weight"] is None

    def test_extract_multiple_fields(self, action, mock_executor):
        """Test extracting multiple fields in one action."""
        mock_element = MagicMock()
        mock_executor.find_element_safe.return_value = mock_element
        mock_executor._extract_value_from_element.side_effect = [
            "Product Name",
            "$29.99",
        ]

        action.execute(
            {
                "fields": [
                    {"name": "Name", "selector": "#title"},
                    {
                        "name": "Price",
                        "selector": ".price",
                        "transform": [
                            {
                                "type": "regex_extract",
                                "pattern": r"\$?([\d.]+)",
                                "group": 1,
                            }
                        ],
                    },
                ]
            }
        )

        assert mock_executor.results["Name"] == "Product Name"
        assert mock_executor.results["Price"] == "29.99"

    def test_transform_strip(self, action, mock_executor):
        """Test strip transformation."""
        mock_element = MagicMock()
        mock_executor.find_element_safe.return_value = mock_element
        mock_executor._extract_value_from_element.return_value = "  padded text  "

        action.execute(
            {
                "fields": [
                    {
                        "name": "Text",
                        "selector": ".text",
                        "transform": [{"type": "strip"}],
                    }
                ]
            }
        )

        assert mock_executor.results["Text"] == "padded text"

    def test_transform_case_changes(self, action, mock_executor):
        """Test lower/upper/title transformations."""
        mock_element = MagicMock()
        mock_executor.find_element_safe.return_value = mock_element

        # Test lower
        mock_executor._extract_value_from_element.return_value = "UPPERCASE TEXT"
        action.execute(
            {
                "fields": [
                    {
                        "name": "Lower",
                        "selector": ".text",
                        "transform": [{"type": "lower"}],
                    }
                ]
            }
        )
        assert mock_executor.results["Lower"] == "uppercase text"

        # Test upper
        mock_executor._extract_value_from_element.return_value = "lowercase text"
        action.execute(
            {
                "fields": [
                    {
                        "name": "Upper",
                        "selector": ".text",
                        "transform": [{"type": "upper"}],
                    }
                ]
            }
        )
        assert mock_executor.results["Upper"] == "LOWERCASE TEXT"

        # Test title
        mock_executor._extract_value_from_element.return_value = "some product name"
        action.execute(
            {
                "fields": [
                    {
                        "name": "Title",
                        "selector": ".text",
                        "transform": [{"type": "title"}],
                    }
                ]
            }
        )
        assert mock_executor.results["Title"] == "Some Product Name"

    def test_chained_transforms(self, action, mock_executor):
        """Test multiple transformations applied in sequence."""
        mock_element = MagicMock()
        mock_executor.find_element_safe.return_value = mock_element
        mock_executor._extract_value_from_element.return_value = (
            "  Visit the ACME BRAND Store  "
        )

        action.execute(
            {
                "fields": [
                    {
                        "name": "Brand",
                        "selector": "#byline",
                        "transform": [
                            {"type": "strip"},
                            {
                                "type": "regex_extract",
                                "pattern": "Visit the (.+) Store",
                                "group": 1,
                            },
                            {"type": "title"},
                        ],
                    }
                ]
            }
        )

        assert mock_executor.results["Brand"] == "Acme Brand"

    def test_deduplication_for_multiple(self, action, mock_executor):
        """Test that multiple extraction deduplicates values."""
        mock_elements = [MagicMock(), MagicMock(), MagicMock()]
        mock_executor.find_elements_safe.return_value = mock_elements
        mock_executor._extract_value_from_element.side_effect = [
            "image1.jpg",
            "image1.jpg",  # Duplicate
            "image2.jpg",
        ]

        action.execute(
            {"fields": [{"name": "Images", "selector": "img", "multiple": True}]}
        )

        assert mock_executor.results["Images"] == ["image1.jpg", "image2.jpg"]

    def test_missing_fields_param_raises(self, action):
        """Test that missing fields parameter raises error."""
        from scrapers.exceptions import WorkflowExecutionError

        with pytest.raises(WorkflowExecutionError, match="requires 'fields'"):
            action.execute({})

    def test_missing_name_raises(self, action):
        """Test that field without name raises error."""
        from scrapers.exceptions import WorkflowExecutionError

        with pytest.raises(WorkflowExecutionError, match="missing 'name'"):
            action.execute({"fields": [{"selector": ".test"}]})

    def test_missing_selector_raises(self, action):
        """Test that field without selector raises error."""
        from scrapers.exceptions import WorkflowExecutionError

        with pytest.raises(WorkflowExecutionError, match="missing 'selector'"):
            action.execute({"fields": [{"name": "Test"}]})
