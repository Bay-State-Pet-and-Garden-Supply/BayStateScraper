from __future__ import annotations

import asyncio

from scrapers.ai_discovery import AIDiscoveryScraper


def test_build_search_query_includes_category_when_present() -> None:
    scraper = AIDiscoveryScraper()

    query = scraper._build_search_query(
        sku="12345",
        product_name="Squeaky Ball",
        brand="Acme Pets",
        category="Dog Toys",
    )

    assert "Acme Pets" in query
    assert "Squeaky Ball" in query
    assert "Dog Toys" in query
    assert "12345" in query
    assert "product" in query
    assert "details" in query


def test_validate_extraction_match_rejects_low_confidence() -> None:
    scraper = AIDiscoveryScraper(confidence_threshold=0.8)

    ok, reason = scraper._validate_extraction_match(
        extraction_result={
            "success": True,
            "product_name": "Acme Squeaky Ball",
            "brand": "Acme",
            "description": "A dog toy",
            "size_metrics": "Large",
            "images": ["https://example.com/image.jpg"],
            "categories": ["Dog Toys"],
            "confidence": 0.7,
        },
        sku="12345",
        product_name="Acme Squeaky Ball",
        brand="Acme",
        source_url="https://acmepets.com/products/12345",
    )

    assert ok is False
    assert "Confidence below threshold" in reason


def test_validate_extraction_match_rejects_brand_mismatch() -> None:
    scraper = AIDiscoveryScraper(confidence_threshold=0.5)

    ok, reason = scraper._validate_extraction_match(
        extraction_result={
            "success": True,
            "product_name": "Acme Squeaky Ball",
            "brand": "Random Brand",
            "description": "A dog toy",
            "size_metrics": "Large",
            "images": ["https://example.com/image.jpg"],
            "categories": ["Dog Toys"],
            "confidence": 0.9,
        },
        sku="12345",
        product_name="Acme Squeaky Ball",
        brand="Acme",
        source_url="https://randomsource.com/products/12345",
    )

    assert ok is False
    assert reason == "Brand mismatch with expected product context"


def test_prepare_search_results_deprioritizes_low_quality_links() -> None:
    scraper = AIDiscoveryScraper()
    results = [
        {
            "url": "https://example.com/blog/best-dog-toys-2026",
            "title": "Best dog toys 2026 review",
            "description": "Top 10 list",
        },
        {
            "url": "https://acmepets.com/products/12345-squeaky-ball",
            "title": "Acme Squeaky Ball Product Page",
            "description": "Official product details",
        },
    ]

    prepared = scraper._prepare_search_results(
        search_results=results,
        sku="12345",
        brand="Acme",
        product_name="Squeaky Ball",
        category="Dog Toys",
    )

    assert prepared[0]["url"] == "https://acmepets.com/products/12345-squeaky-ball"


def test_scrape_product_rejects_unrelated_extraction_and_fails() -> None:
    class StubScraper(AIDiscoveryScraper):
        async def _search_product(self, query: str) -> tuple[list[dict[str, str]], str | None]:
            _ = query
            return [
                {
                    "url": "https://wrongbrand.com/products/999",
                    "title": "Wrong Brand Toy",
                    "description": "Not the requested product",
                }
            ], None

        async def _identify_best_source(
            self,
            search_results: list[dict[str, str]],
            sku: str,
            brand: str | None,
            product_name: str | None,
        ) -> str | None:
            _ = (sku, brand, product_name)
            return search_results[0]["url"] if search_results else None

        async def _extract_product_data(
            self,
            url: str,
            sku: str,
            product_name: str | None,
            brand: str | None,
        ) -> dict[str, object]:
            _ = (url, sku, product_name, brand)
            return {
                "success": True,
                "product_name": "Unrelated Product",
                "brand": "Wrong Brand",
                "description": "Unrelated",
                "size_metrics": "N/A",
                "images": ["https://wrongbrand.com/image.jpg"],
                "categories": ["Dog Toys"],
                "confidence": 0.95,
            }

    scraper = StubScraper(confidence_threshold=0.7)

    result = asyncio.run(
        scraper.scrape_product(
            sku="12345",
            product_name="Acme Squeaky Ball",
            brand="Acme",
            category="Dog Toys",
        )
    )

    assert result.success is False
    assert result.error is not None
    assert "rejected" in result.error.lower() or "mismatch" in result.error.lower()
