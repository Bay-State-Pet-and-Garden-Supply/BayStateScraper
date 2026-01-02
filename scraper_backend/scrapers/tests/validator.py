"""
Scraper output validation utilities for testing and debugging.
"""
from __future__ import annotations


import re
from typing import Any, TypedDict

import pandas as pd

MAX_SKU_LENGTH = 50
MIN_WEIGHT = 0.01
MAX_WEIGHT = 1000.0
MAX_ERRORS_TO_SHOW = 10


class ValidationResults(TypedDict):
    scraper: str
    total_products: int
    valid_products: int
    invalid_products: int
    errors: list[str]
    warnings: list[str]
    field_coverage: dict[str, float]
    data_quality_score: float


class DataFrameValidationResults(TypedDict):
    scraper: str
    dataframe_shape: tuple[int, int]
    columns: list[str]
    errors: list[str]
    warnings: list[str]


class ScraperValidator:
    """Validates scraper output data format and content."""

    def __init__(self, test_data_path: str | None = None):
        """Initialize validator with test data configuration."""
        # Define common validation rules internally
        self.common_rules = {
            "required_fields": ["SKU", "Name"],
            "weight_unit": "LB",
            "image_format": "list_of_urls",
            "price_format": "string",
            "invalid_values": ["N/A", "n/a", "NA", "null", "NULL", ""],
        }

        # Define expected fields for each scraper
        self.expected_fields = {
            "amazon": ["SKU", "Name", "Brand", "Weight", "Image URLs"],
            "bradley": ["SKU", "Name", "Brand", "Weight", "Image URLs"],
            "central_pet": ["SKU", "Name", "Brand", "Weight", "Image URLs"],
            "coastal": ["SKU", "Name", "Brand", "Image URLs"],
            "mazuri": ["SKU", "Name", "Brand", "Weight", "Image URLs"],
            "petfoodex": ["SKU", "Name", "Brand", "Weight", "Image URLs"],
            "phillips": ["SKU", "Name", "Brand", "Weight", "Image URLs"],
            "orgill": ["SKU", "Name", "Brand", "Weight", "Image URLs"],
        }

    def _validate_product_fields(
        self, product: dict, expected_fields: list[str], field_counts: dict[str, int]
    ) -> tuple[list[str], list[str]]:
        product_errors = []
        product_warnings = []

        # Check required fields
        for field in self.common_rules.get("required_fields", []):
            if field not in product or product[field] is None:
                product_errors.append(f"Missing required field: {field}")
            elif str(product[field]).strip() in self.common_rules.get("invalid_values", []):
                product_errors.append(
                    f"Invalid value for required field {field}: '{product[field]}'"
                )

        # Check expected fields and field-specific validation
        for field in expected_fields:
            if field in product:
                field_counts[field] += 1
                if field == "SKU" and not self._validate_sku(product[field]):
                    product_warnings.append(f"SKU format may be invalid: {product[field]}")
                elif field == "Price" and not self._validate_price(product[field]):
                    product_warnings.append(f"Price format may be invalid: {product[field]}")
                elif field == "Images" and not self._validate_images(product[field]):
                    product_warnings.append(f"Images format may be invalid: {product[field]}")
                elif field == "Weight" and not self._validate_weight(product[field]):
                    product_warnings.append(f"Weight format may be invalid: {product[field]}")
        return product_errors, product_warnings

    def validate_product_data(self, products: list[dict], scraper_name: str) -> ValidationResults:
        """
        Validate a list of product dictionaries from a scraper.

        Args:
            products: List of product dictionaries
            scraper_name: Name of the scraper

        Returns:
            Dict with validation results and any errors found
        """
        results: ValidationResults = {
            "scraper": scraper_name,
            "total_products": len(products),
            "valid_products": 0,
            "invalid_products": 0,
            "errors": [],
            "warnings": [],
            "field_coverage": {},
            "data_quality_score": 0.0,
        }

        if not products:
            results["errors"].append("No products returned")
            return results

        expected_fields = self.expected_fields.get(scraper_name, [])
        field_counts = {field: 0 for field in expected_fields}

        for i, product in enumerate(products):
            if not isinstance(product, dict):
                results["errors"].append(f"Product {i}: Not a dictionary (type: {type(product)})")
                results["invalid_products"] += 1
                continue

            product_errors, product_warnings = self._validate_product_fields(
                product, expected_fields, field_counts
            )

            if not product_errors:
                results["valid_products"] += 1
            else:
                results["invalid_products"] += 1
                results["errors"].extend([f"Product {i}: {err}" for err in product_errors])

            if product_warnings:
                results["warnings"].extend([f"Product {i}: {warn}" for warn in product_warnings])

        # Calculate field coverage and data quality score
        if results["total_products"] > 0:
            results["field_coverage"] = {
                field: (count / results["total_products"]) * 100
                for field, count in field_counts.items()
            }
            valid_ratio = results["valid_products"] / results["total_products"]
            field_coverage_avg = (
                sum(results["field_coverage"].values()) / len(results["field_coverage"])
                if results["field_coverage"]
                else 0
            )
            results["data_quality_score"] = valid_ratio * 0.6 + (field_coverage_avg / 100) * 0.4

        return results

    def validate_dataframe_output(
        self, df: pd.DataFrame, scraper_name: str
    ) -> DataFrameValidationResults:
        """
        Validate pandas DataFrame output from scraper.

        Args:
            df: Pandas DataFrame with product data
            scraper_name: Name of the scraper

        Returns:
            Dict with validation results
        """
        results: DataFrameValidationResults = {
            "scraper": scraper_name,
            "dataframe_shape": df.shape,
            "columns": list(df.columns),
            "errors": [],
            "warnings": [],
        }

        if df.empty:
            results["errors"].append("DataFrame is empty")
            return results

        expected_fields = self.expected_fields.get(scraper_name, [])

        # Check for expected columns
        missing_columns = set(expected_fields) - set(df.columns)
        if missing_columns:
            results["warnings"].append(f"Missing expected columns: {list(missing_columns)}")

        # Check for required columns
        required_fields = self.common_rules.get("required_fields", [])
        missing_required = set(required_fields) - set(df.columns)
        if missing_required:
            results["errors"].append(f"Missing required columns: {list(missing_required)}")

        # Validate each row
        for idx, row in df.iterrows():
            row_errors = []
            for field in required_fields:
                if field in df.columns:
                    value = row[field]
                    if pd.isna(value) or str(value).strip() in self.common_rules.get(
                        "invalid_values", []
                    ):
                        row_errors.append(f"Row {idx}: Invalid {field} value: '{value}'")

            if row_errors:
                results["errors"].extend(row_errors)

        return results

    def _validate_sku(self, sku: Any) -> bool:
        """Validate SKU format."""
        if not sku:
            return False
        sku_str = str(sku).strip()
        return 1 <= len(sku_str) <= MAX_SKU_LENGTH

    def _validate_price(self, price: Any) -> bool:
        """Validate price format."""
        if not price:
            return False
        price_str = str(price).strip()
        price_pattern = r"^\$?\d+(\.\d{1,2})?$"
        return bool(re.match(price_pattern, price_str))

    def _validate_images(self, images: Any) -> bool:
        """Validate images format (list of URLs)."""
        if not images:
            return False

        if isinstance(images, list):
            image_list = images
        elif isinstance(images, str):
            image_list = [url.strip() for url in images.split(",") if url.strip()]
        else:
            return False

        if not image_list:
            return False

        url_pattern = r"^https?://[^\s,]+$"
        return all(re.match(url_pattern, str(url)) for url in image_list if url)

    def _validate_weight(self, weight: Any) -> bool:
        """Validate weight format (should be in LB units)."""
        if not weight:
            return False
        weight_str = str(weight).strip().upper()

        if "LB" not in weight_str and "POUND" not in weight_str:
            return False

        weight_match = re.search(r"(\d+(?:\.\d+)?)", weight_str)
        if not weight_match:
            return False

        weight_value = float(weight_match.group(1))
        return MIN_WEIGHT <= weight_value <= MAX_WEIGHT

    def print_validation_report(self, results: dict[str, Any]) -> None:
        """Print a formatted validation report."""
        print(f"\n{'=' * 60}")
        print(f"VALIDATION REPORT: {results['scraper'].upper()}")
        print(f"{'=' * 60}")

        print(f"Total Products: {results['total_products']}")
        print(f"Valid Products: {results['valid_products']}")
        print(f"Invalid Products: {results['invalid_products']}")
        print(f"Data Quality Score: {results['data_quality_score']:.1f}")

        if results.get("dataframe_shape"):
            print(f"DataFrame Shape: {results['dataframe_shape']}")

        if results["field_coverage"]:
            print("\nField Coverage:")
            for field, coverage in results["field_coverage"].items():
                print(f"  {field}: {coverage:.1f}%")

        if results["errors"]:
            print(f"\nERRORS ({len(results['errors'])}):")
            for error in results["errors"][:MAX_ERRORS_TO_SHOW]:
                print(f"  - {error}")
            if len(results["errors"]) > MAX_ERRORS_TO_SHOW:
                print(f"  ... and {len(results['errors']) - MAX_ERRORS_TO_SHOW} more errors")

        if results["warnings"]:
            print(f"\nWARNINGS ({len(results['warnings'])}):")
            for warning in results["warnings"][:MAX_ERRORS_TO_SHOW]:
                print(f"  - {warning}")
            if len(results["warnings"]) > MAX_ERRORS_TO_SHOW:
                print(f"  ... and {len(results['warnings']) - MAX_ERRORS_TO_SHOW} more warnings")

        if results["errors"]:
            print("\nVALIDATION FAILED - Fix errors before deployment")
        elif results["warnings"]:
            print("\nVALIDATION PASSED WITH WARNINGS - Review warnings")
        else:
            print("\nVALIDATION PASSED - Ready for deployment")

        print(f"{'=' * 60}\n")
