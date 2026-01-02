"""
Scraper Validator for testing product data quality.
"""
from __future__ import annotations


import logging
from typing import Any

logger = logging.getLogger(__name__)


class ScraperValidator:
    """Validates scraped product data for quality and completeness."""

    def __init__(self):
        """Initialize the validator."""
        pass

    def validate_product_data(
        self, products: list[dict[str, Any]], scraper_name: str
    ) -> dict[str, Any]:
        """
        Validate a list of product data from a scraper.

        Args:
            products: List of product dictionaries
            scraper_name: Name of the scraper

        Returns:
            Validation results dictionary
        """
        if not products:
            return {
                "errors": ["No products to validate"],
                "warnings": [],
                "score": 0.0,
                "total_products": 0,
                "valid_products": 0,
            }

        errors = []
        warnings = []
        valid_count = 0

        for i, product in enumerate(products):
            product_errors = []
            product_warnings = []

            # Check required fields
            required_fields = ["Name", "SKU"]
            for field in required_fields:
                field_val = product.get(field)
                if not field_val:
                    product_errors.append(f"Missing required field: {field}")
                elif not isinstance(field_val, str) or not field_val.strip():
                    product_errors.append(f"Empty or invalid {field}")

            # Check SKU format (basic validation)
            sku = product.get("SKU", "")
            if sku and not (isinstance(sku, str) and len(sku.strip()) > 0):
                product_errors.append("Invalid SKU format")

            # Check for reasonable name length
            name = product.get("Name", "")
            if name and len(name.strip()) < 3:
                product_warnings.append("Product name seems too short")

            # Check images if present
            images = product.get("Images", [])
            if images and not isinstance(images, list):
                product_errors.append("Images field should be a list")
            elif images and len(images) == 0:
                product_warnings.append("No images found")

            # Check brand if present
            brand = product.get("Brand", "")
            if brand and len(brand.strip()) < 2:
                product_warnings.append("Brand name seems too short")

            if not product_errors:
                valid_count += 1
            else:
                errors.extend([f"Product {i + 1}: {err}" for err in product_errors])

            if product_warnings:
                warnings.extend([f"Product {i + 1}: {warn}" for warn in product_warnings])

        # Calculate score based on valid products
        total_products = len(products)
        score = (valid_count / total_products * 100) if total_products > 0 else 0.0

        return {
            "errors": errors,
            "warnings": warnings,
            "score": score,
            "total_products": total_products,
            "valid_products": valid_count,
        }
