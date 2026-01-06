"""
Unified Product Data Models

This module defines Pydantic models for the entire product data pipeline:
- ExcelInputProduct: Source of truth for SKU and Price (FROZEN)
- RawScrapedProduct: Scraper output with auto-cleaning validators

CRITICAL: SKU and Price from Excel are immutable throughout the pipeline.
Scrapers and LLM consolidation only provide enrichment data (name, brand, etc.).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# =============================================================================
# FROZEN FIELDS MODEL - Source of Truth from Excel
# =============================================================================


class ExcelInputProduct(BaseModel):
    """
    Product data imported from Excel (register system export).

    CRITICAL: SKU and Price are the SOURCE OF TRUTH and must NEVER be
    overwritten by scrapers or LLM consolidation.

    Attributes:
        sku: Product SKU - PRIMARY KEY, never changes throughout pipeline
        price: Register price - FROZEN, never overwritten by scrapers/LLM
        existing_name: Optional current name from register (for reference)
    """

    model_config = ConfigDict(frozen=True)  # Immutable!

    sku: str = Field(..., description="Product SKU - PRIMARY KEY, never changes")
    price: str = Field(..., description="Register price - FROZEN, never overwritten")

    # Optional metadata from Excel
    existing_name: str | None = Field(
        default=None, description="Current name in register"
    )

    def __hash__(self) -> int:
        """Allow use in sets and as dict keys."""
        return hash(self.sku)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ExcelInputProduct):
            return self.sku == other.sku
        return False


# =============================================================================
# SCRAPER OUTPUT MODEL - Enrichment Data Only
# =============================================================================


class RawScrapedProduct(BaseModel):
    """
    Raw product data as scraped. Lenient validation with auto-cleaning.

    NOTE: Any 'scraped_price' here is for REFERENCE ONLY and will NOT
    be used in the final product. Excel price is the source of truth.

    Attributes:
        sku: Reference to Excel SKU
        source: Which scraper produced this (e.g., "amazon", "chewy")
        name: Product name as scraped
        brand: Brand name as scraped
        weight: Product weight (auto-cleaned from strings like "5 lbs")
        description: Product description
        images: List of image URLs
        scraped_price: Reference only - NOT used in final product
        image_quality: Quality score for images (0-100)
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    sku: str  # Reference to Excel SKU
    source: str  # Which scraper produced this (e.g., "amazon", "chewy")

    # Enrichment fields (these CAN be used in consolidation)
    name: str | None = None
    brand: str | None = None
    weight: float | None = None
    description: str | None = None
    images: list[str] = Field(default_factory=list)
    category: str | None = None
    product_type: str | None = None

    # Scraped price is stored but IGNORED in final output
    scraped_price: float | None = Field(
        default=None, description="Reference only - NOT used in final product"
    )

    # Metadata
    image_quality: int = Field(default=50, ge=0, le=100)

    @field_validator("scraped_price", mode="before")
    @classmethod
    def clean_price(cls, v: Any) -> float | None:
        """Clean price string to float. For reference only."""
        if v is None:
            return None
        if isinstance(v, str):
            clean = "".join(c for c in v if c.isdigit() or c == ".")
            return float(clean) if clean else None
        return float(v) if v else None

    @field_validator("weight", mode="before")
    @classmethod
    def clean_weight(cls, v: Any) -> float | None:
        """Clean weight string like '5 lbs' to float."""
        if v is None:
            return None
        if isinstance(v, str):
            clean = "".join(c for c in v if c.isdigit() or c == ".")
            return float(clean) if clean else None
        return float(v) if v else None

    @field_validator("images", mode="before")
    @classmethod
    def validate_images(cls, v: Any) -> list[str]:
        """Filter to only valid HTTP URLs."""
        if not v:
            return []
        if isinstance(v, list):
            return [url for url in v if isinstance(url, str) and url.startswith("http")]
        return []

    def to_db_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary for database storage.
        Uses legacy field names for backward compatibility.
        """
        return {
            "Name": self.name,
            "Brand": self.brand,
            "Weight": str(self.weight) if self.weight else None,
            "Images": self.images,
            "Description": self.description,
            "Category": self.category,
            "ProductType": self.product_type,
            # Scraped price stored for reference but marked clearly
            "ScrapedPrice": self.scraped_price,
        }
