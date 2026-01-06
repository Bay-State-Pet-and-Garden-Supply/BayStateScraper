"""
Unified Product Data Models

This module defines Pydantic models for the entire product data pipeline:
- ExcelInputProduct: Source of truth for SKU and Price (FROZEN)
- RawScrapedProduct: Scraper output with auto-cleaning validators
- ConsolidatedProduct: LLM-merged data combined with frozen Excel fields
- ShopSiteProduct: Final export format for ShopSite XML

CRITICAL: SKU and Price from Excel are immutable throughout the pipeline.
Scrapers and LLM consolidation only provide enrichment data (name, brand, etc.).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# =============================================================================
# ENUMS
# =============================================================================


class SourceTrust(str, Enum):
    """Trust levels for data sources used in consolidation."""

    HIGH = "high"  # Verified/official sources (brand sites, distributors)
    MEDIUM = "medium"  # Reliable retailers (Amazon, Chewy, Home Depot)
    LOW = "low"  # Less reliable or unknown sources


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
    existing_name: str | None = Field(default=None, description="Current name in register")

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


# =============================================================================
# CONSOLIDATED PRODUCT MODEL - LLM Output + Frozen Fields
# =============================================================================


class ConsolidatedProduct(BaseModel):
    """
    Product after LLM consolidation, merged with frozen Excel fields.

    IMPORTANT:
    - 'sku' comes from Excel (frozen)
    - 'price' comes from Excel (frozen)
    - All other fields are enriched from scrapers + LLM

    Use `from_llm_result()` factory method to ensure frozen fields
    always come from Excel.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    # FROZEN FIELDS (from Excel - never modified by LLM)
    sku: str = Field(..., description="From Excel - FROZEN")
    price: str = Field(..., description="From Excel - FROZEN")

    # ENRICHMENT FIELDS (from Scrapers + LLM)
    name: str = Field(default="", description="Consolidated from scrapers/LLM")
    brand: str = ""
    weight: str = ""  # Stored as formatted string "30.00"
    images: list[str] = Field(default_factory=list)
    category: str = ""
    product_type: str = ""
    product_on_pages: str = ""
    description: str = ""

    # Confidence metadata
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    field_confidences: dict[str, float] = Field(default_factory=dict)
    source_notes: str = ""
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_llm_result(
        cls,
        llm_output: dict[str, Any],
        excel_input: ExcelInputProduct,
    ) -> ConsolidatedProduct:
        """
        Create ConsolidatedProduct by merging LLM output with frozen Excel fields.

        This is the RECOMMENDED way to create a ConsolidatedProduct to ensure
        SKU and Price always come from Excel.

        Args:
            llm_output: Dictionary from LLM consolidation response
            excel_input: ExcelInputProduct with frozen SKU and Price

        Returns:
            ConsolidatedProduct with frozen fields from Excel and
            enrichment from LLM
        """
        return cls(
            # FROZEN from Excel
            sku=excel_input.sku,
            price=excel_input.price,
            # ENRICHED from LLM
            name=llm_output.get("name", ""),
            brand=llm_output.get("brand", ""),
            weight=llm_output.get("weight", ""),
            images=llm_output.get("images", []),
            category=llm_output.get("category", ""),
            product_type=llm_output.get("product_type", ""),
            product_on_pages=llm_output.get("product_on_pages", ""),
            description=llm_output.get("description", ""),
            confidence_score=llm_output.get("confidence_score", 0.0),
            field_confidences=llm_output.get("field_confidences", {}),
            source_notes=llm_output.get("source_notes", ""),
            warnings=llm_output.get("warnings", []),
        )

    @classmethod
    def from_dict_with_frozen_fields(
        cls,
        data: dict[str, Any],
        frozen_sku: str,
        frozen_price: str,
    ) -> ConsolidatedProduct:
        """
        Create from dictionary while enforcing frozen fields.

        Alternative to from_llm_result when ExcelInputProduct is not available.

        Args:
            data: Dictionary with product data
            frozen_sku: SKU from Excel (will override any sku in data)
            frozen_price: Price from Excel (will override any price in data)

        Returns:
            ConsolidatedProduct with enforced frozen fields
        """
        # Override any sku/price in data with frozen values
        data = data.copy()
        data["sku"] = frozen_sku
        data["price"] = frozen_price
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return self.model_dump()


# =============================================================================
# SHOPSITE EXPORT MODEL - Final XML Output
# =============================================================================


class ShopSiteProduct(BaseModel):
    """
    Final product ready for ShopSite XML export.
    Uses PascalCase field names to match ShopSite requirements.

    Create using `from_consolidated()` to maintain the frozen field chain.
    """

    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    SKU: str = Field(..., alias="sku")
    Name: str = Field(..., alias="name")
    Brand: str = Field(default="", alias="brand")
    Price: str = Field(..., alias="price")
    Weight: str = Field(default="", alias="weight")
    Description: str = Field(default="", alias="description")
    Category: str = Field(default="", alias="category")
    ProductType: str = Field(default="", alias="product_type")
    ProductOnPages: str = Field(default="", alias="product_on_pages")
    Images: list[str] = Field(default_factory=list, alias="images")

    @classmethod
    def from_consolidated(cls, consolidated: ConsolidatedProduct) -> ShopSiteProduct:
        """
        Convert a ConsolidatedProduct to ShopSiteProduct format.

        This maintains the frozen field chain:
        Excel -> ConsolidatedProduct -> ShopSiteProduct

        Args:
            consolidated: ConsolidatedProduct with frozen SKU/Price

        Returns:
            ShopSiteProduct ready for XML export
        """
        return cls(
            SKU=consolidated.sku,
            Name=consolidated.name,
            Brand=consolidated.brand,
            Price=consolidated.price,  # Comes from Excel via ConsolidatedProduct
            Weight=consolidated.weight,
            Description=consolidated.description,
            Category=consolidated.category,
            ProductType=consolidated.product_type,
            ProductOnPages=consolidated.product_on_pages,
            Images=consolidated.images,
        )

    def to_xml_dict(self) -> dict[str, Any]:
        """
        Return dict with ShopSite-compatible field names.

        Returns:
            Dictionary with PascalCase keys matching ShopSite XML schema
        """
        return {
            "SKU": self.SKU,
            "Name": self.Name,
            "Brand": self.Brand,
            "Price": self.Price,
            "Weight": self.Weight,
            "Description": self.Description,
            "Category": self.Category,
            "ProductType": self.ProductType,
            "ProductOnPages": self.ProductOnPages,
            "Images": self.Images,
        }


# =============================================================================
# BACKWARD COMPATIBILITY ALIAS
# =============================================================================

# Alias for backward compatibility with existing consolidation code
ConsolidationResult = ConsolidatedProduct
