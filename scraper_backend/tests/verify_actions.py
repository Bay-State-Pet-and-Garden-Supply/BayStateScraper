import os
import sys
import unittest
from typing import cast
from unittest.mock import MagicMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

# Import action handlers to register them
import scraper_backend.scrapers.actions.handlers.combine_fields
import scraper_backend.scrapers.actions.handlers.extract_from_json
import scraper_backend.scrapers.actions.handlers.parse_weight
import scraper_backend.scrapers.actions.handlers.transform_value
import scraper_backend.scrapers.actions.handlers.verify
from scraper_backend.scrapers.actions.base import BaseAction
from scraper_backend.scrapers.actions.registry import ActionRegistry
from scraper_backend.scrapers.executor.workflow_executor import WorkflowExecutor


class TestScraperActions(unittest.TestCase):
    def setUp(self):
        self.mock_executor = MagicMock(spec=WorkflowExecutor)
        self.mock_executor.results = {}
        self.mock_executor.browser = MagicMock()
        self.mock_executor.config = MagicMock()

    def test_registry(self):
        """Test that actions are registered."""
        actions = ActionRegistry.get_registered_actions()
        print(f"Registered actions: {list(actions.keys())}")
        self.assertIn("navigate", actions)
        self.assertIn("extract_single", actions)
        self.assertIn("combine_fields", actions)
        self.assertIn("transform_value", actions)

    def test_combine_fields(self):
        """Test combine_fields action."""
        action_cls = ActionRegistry.get_action_class("combine_fields")
        if action_cls is None:
            self.fail("Action combine_fields not found")
        action = action_cls(self.mock_executor)

        self.mock_executor.results = {"brand": "Acme", "name": "Widget"}
        params = {
            "target_field": "full_name",
            "format": "{brand} {name}",
            "fields": ["brand", "name"],
        }
        action.execute(params)
        self.assertEqual(self.mock_executor.results["full_name"], "Acme Widget")

    def test_transform_value(self):
        """Test transform_value action."""
        action_cls = ActionRegistry.get_action_class("transform_value")
        if action_cls is None:
            self.fail("Action transform_value not found")
        action = action_cls(self.mock_executor)

        self.mock_executor.results = {"price": "$10.00"}
        params = {
            "field": "price",
            "transformations": [
                {"type": "replace", "pattern": "\\$", "replacement": ""},
                {"type": "strip", "chars": " "},
            ],
        }
        action.execute(params)
        self.assertEqual(self.mock_executor.results["price"], "10.00")

    def test_extract_from_json(self):
        """Test extract_from_json action."""
        action_cls = ActionRegistry.get_action_class("extract_from_json")
        if action_cls is None:
            self.fail("Action extract_from_json not found")
        action = action_cls(self.mock_executor)

        json_data = '{"product": {"price": 20.5}}'
        self.mock_executor.results = {"json_script": json_data}
        params = {
            "source_field": "json_script",
            "target_field": "price",
            "json_path": "product.price",
        }
        action.execute(params)
        self.assertEqual(self.mock_executor.results["price"], 20.5)

    def test_parse_weight(self):
        """Test parse_weight action."""
        action_cls = ActionRegistry.get_action_class("parse_weight")
        if action_cls is None:
            self.fail("Action parse_weight not found")
        action = action_cls(self.mock_executor)

        self.mock_executor.results = {"weight": "16 oz"}
        params = {"field": "weight", "target_unit": "lb"}
        action.execute(params)
        self.assertEqual(self.mock_executor.results["weight"], "1.00 lb")

    def test_verify_value(self):
        """Test verify_value action."""
        action_cls = ActionRegistry.get_action_class("verify_value")
        if action_cls is None:
            self.fail("Action verify_value not found")
        action = action_cls(self.mock_executor)

        self.mock_executor.results = {"sku": "12345"}
        params = {"field": "sku", "expected": "12345", "match_mode": "exact"}
        # Should not raise error
        action.execute(params)

        params["expected"] = "67890"
        with self.assertRaises(Exception):  # Should raise WorkflowExecutionError
            action.execute(params)


if __name__ == "__main__":
    unittest.main()
