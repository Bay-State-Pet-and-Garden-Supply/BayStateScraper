"""
AI Discovery Scraper - Universal product extraction.

This module provides a standalone AI scraper that:
1. Searches for products using Brave Search API
2. Identifies manufacturer websites intelligently
3. Navigates and extracts product data
4. Returns structured results

Usage:
    from scrapers.ai_discovery import AIDiscoveryScraper

    scraper = AIDiscoveryScraper()
    result = await scraper.scrape_product(
        sku="12345",
        product_name="Purina Pro Plan",
        brand="Purina"
    )
"""

import asyncio
import json
import logging
from typing import Any, Optional
from dataclasses import dataclass
from urllib.parse import urlparse
from collections import OrderedDict

from scrapers.ai_cost_tracker import AICostTracker
from scrapers.ai_metrics import record_ai_extraction, record_ai_fallback
from scrapers.actions.handlers.ai_base import BaseAIAction

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryResult:
    """Result from AI discovery scraping."""

    success: bool
    sku: str
    product_name: Optional[str] = None
    brand: Optional[str] = None
    price: Optional[str] = None
    description: Optional[str] = None
    images: Optional[list[str]] = None
    availability: Optional[str] = None
    url: Optional[str] = None
    source_website: Optional[str] = None
    confidence: float = 0.0
    cost_usd: float = 0.0
    error: Optional[str] = None

    def __post_init__(self):
        if self.images is None:
            self.images = []


class AIDiscoveryScraper:
    """AI-powered discovery scraper for universal product extraction.

    This scraper doesn't require pre-configured site definitions. Instead, it:
    1. Searches for the product using Brave Search API
    2. Uses AI to identify the most likely manufacturer/official product page
    3. Navigates to that page and extracts structured data
    4. Returns results in a standardized format
    """

    def __init__(
        self,
        headless: bool = True,
        max_search_results: int = 5,
        max_steps: int = 15,
        confidence_threshold: float = 0.7,
        llm_model: str = "gpt-4o-mini",
    ):
        """Initialize the AI discovery scraper.

        Args:
            headless: Whether to run browser in headless mode
            max_search_results: Number of search results to analyze
            max_steps: Maximum browser actions per extraction
            confidence_threshold: Minimum confidence score to accept result
            llm_model: LLM model to use for AI extraction
        """
        self.headless = headless
        self.max_search_results = max_search_results
        self.max_steps = max_steps
        self.confidence_threshold = confidence_threshold
        self.llm_model = llm_model
        self._cost_tracker = AICostTracker()
        self._browser: Any = None
        self._llm: Any = None
        self._search_cache: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        self._search_cache_max = 500

    async def scrape_products_batch(
        self,
        items: list[dict[str, Any]],
        max_concurrency: int = 4,
    ) -> list[DiscoveryResult]:
        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        async def _run_one(item: dict[str, Any]) -> DiscoveryResult:
            async with semaphore:
                sku = str(item.get("sku", "")).strip()
                if not sku:
                    return DiscoveryResult(success=False, sku="", error="Missing sku")
                return await self.scrape_product(
                    sku=sku,
                    product_name=item.get("product_name"),
                    brand=item.get("brand"),
                    category=item.get("category"),
                )

        return await asyncio.gather(*[_run_one(item) for item in items])

    async def scrape_product(
        self,
        sku: str,
        product_name: Optional[str] = None,
        brand: Optional[str] = None,
        category: Optional[str] = None,
    ) -> DiscoveryResult:
        """Scrape a product using AI discovery.

        Args:
            sku: Product SKU or identifier
            product_name: Product name (optional, helps search)
            brand: Product brand (optional, helps identify manufacturer site)
            category: Product category (optional)

        Returns:
            DiscoveryResult with extracted data
        """
        try:
            # Step 1: Build search query
            search_query = self._build_search_query(sku, product_name, brand)
            logger.info(f"[AI Discovery] Searching for: {search_query}")

            # Step 2: Search for product pages
            search_results = await self._search_product(search_query)
            if not search_results:
                return DiscoveryResult(success=False, sku=sku, error="No search results found")

            # Step 3: Use AI to identify best source (prefer manufacturer website)
            target_url = await self._identify_best_source(search_results, brand, product_name)
            if not target_url:
                return DiscoveryResult(success=False, sku=sku, error="Could not identify suitable product page")

            logger.info(f"[AI Discovery] Selected source: {target_url}")

            # Step 4: Extract product data from the selected page
            extraction_result = await self._extract_product_data(target_url, sku, product_name, brand)

            # Step 5: Record metrics
            cost_summary = self._cost_tracker.get_cost_summary()
            record_ai_extraction(
                scraper_name=f"ai_discovery_{brand or 'unknown'}",
                success=extraction_result.get("success", False),
                cost_usd=cost_summary.get("total_cost_usd", 0),
                duration_seconds=0.0,
                anti_bot_detected=extraction_result.get("anti_bot_detected", False),
            )

            # Build result
            if extraction_result.get("success"):
                return DiscoveryResult(
                    success=True,
                    sku=sku,
                    product_name=extraction_result.get("product_name") or product_name,
                    brand=extraction_result.get("brand") or brand,
                    price=extraction_result.get("price"),
                    description=extraction_result.get("description"),
                    images=extraction_result.get("images", []),
                    availability=extraction_result.get("availability"),
                    url=target_url,
                    source_website=urlparse(target_url).netloc,
                    confidence=extraction_result.get("confidence", 0),
                    cost_usd=cost_summary.get("total_cost_usd", 0),
                )
            else:
                return DiscoveryResult(
                    success=False,
                    sku=sku,
                    error=extraction_result.get("error", "Extraction failed"),
                    cost_usd=cost_summary.get("total_cost_usd", 0),
                )

        except Exception as e:
            logger.error(f"[AI Discovery] Error scraping {sku}: {e}")
            return DiscoveryResult(success=False, sku=sku, error=str(e))

    def _build_search_query(
        self,
        sku: str,
        product_name: Optional[str],
        brand: Optional[str],
    ) -> str:
        """Build an effective search query for the product."""
        parts = []

        if brand:
            parts.append(brand)
        if product_name:
            parts.append(product_name)
        parts.append(sku)

        # Add terms to help find official product pages
        query = " ".join(parts)
        query += " official product site"

        return query

    async def _search_product(self, query: str) -> list[dict[str, Any]]:
        """Search for product using Brave Search API.

        Args:
            query: Search query

        Returns:
            List of search results with url, title, description
        """
        cached = self._cache_get(query)
        if cached is not None:
            return cached

        try:
            import os
            import httpx

            api_key = os.environ.get("BRAVE_API_KEY")
            if not api_key:
                logger.error("BRAVE_API_KEY not set")
                return []

            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            }
            params = {
                "q": query,
                "count": self.max_search_results,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()

            web_results = data.get("web", {}).get("results", [])

            search_results = []
            for result in web_results[: self.max_search_results]:
                if isinstance(result, dict):
                    search_results.append(
                        {
                            "url": result.get("url", ""),
                            "title": result.get("title", ""),
                            "description": result.get("description", ""),
                        }
                    )

            self._cache_set(query, search_results)
            return search_results

        except Exception as e:
            logger.error(f"[AI Discovery] Search failed: {e}")
            return []

    def _cache_get(self, key: str) -> Optional[list[dict[str, Any]]]:
        if key not in self._search_cache:
            return None
        value = self._search_cache.pop(key)
        self._search_cache[key] = value
        return value

    def _cache_set(self, key: str, value: list[dict[str, Any]]) -> None:
        if key in self._search_cache:
            self._search_cache.pop(key)
        self._search_cache[key] = value
        while len(self._search_cache) > self._search_cache_max:
            self._search_cache.popitem(last=False)

    async def _identify_best_source(
        self,
        search_results: list[dict[str, Any]],
        brand: Optional[str],
        product_name: Optional[str],
    ) -> Optional[str]:
        """Use AI to identify the best product page from search results.

        Prefers:
        1. Manufacturer websites (e.g., purina.com for Purina products)
        2. Official product pages
        3. Retailers with comprehensive product info

        Avoids:
        1. Review sites
        2. Comparison shopping sites
        3. Affiliate/marketing sites
        """
        try:
            import os

            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                logger.error("OPENAI_API_KEY not set")
                # Fallback to simple heuristic
                return self._heuristic_source_selection(search_results, brand)

            browser_llm_module = __import__("browser_use.llm", fromlist=["ChatOpenAI"])
            ChatOpenAI = getattr(browser_llm_module, "ChatOpenAI")

            llm = ChatOpenAI(
                model=self.llm_model,
                api_key=api_key,
                temperature=0,
            )

            # Build the selection prompt
            results_text = "\n\n".join(
                [
                    f"{i + 1}. URL: {r['url']}\nTitle: {r['title']}\nDescription: {r['description']}"
                    for i, r in enumerate(search_results[: self.max_search_results])
                ]
            )

            prompt = f"""Given these search results for a product, identify the BEST official product page.

Product Brand: {brand or "Unknown"}
Product Name: {product_name or "Unknown"}

Search Results:
{results_text}

Rank the results by preference:
1. Manufacturer/brand official website (e.g., purina.com for Purina products)
2. Official product page with complete specs
3. Major retailer with comprehensive product info

AVOID:
- Review sites
- Comparison shopping sites  
- Affiliate marketing sites
- Sites with thin content

Respond with ONLY the number (1-{len(search_results)}) of the best result, or 0 if none are suitable."""

            response = await llm.ainvoke(prompt)
            response_text = response.content if hasattr(response, "content") else str(response)

            try:
                selection = int(response_text.strip())
                if 1 <= selection <= len(search_results):
                    return search_results[selection - 1]["url"]
            except ValueError:
                logger.warning(f"[AI Discovery] Could not parse AI selection: {response_text}")

            # Fallback to heuristic
            return self._heuristic_source_selection(search_results, brand)

        except Exception as e:
            logger.error(f"[AI Discovery] Source identification failed: {e}")
            return self._heuristic_source_selection(search_results, brand)

    def _heuristic_source_selection(
        self,
        search_results: list[dict[str, Any]],
        brand: Optional[str],
    ) -> Optional[str]:
        """Fallback heuristic to select best source without AI."""
        if not search_results:
            return None

        if not brand:
            # Just return first result
            return search_results[0]["url"]

        brand_lower = brand.lower().replace(" ", "")

        # Look for manufacturer website
        for result in search_results:
            url = result["url"].lower()
            if brand_lower in url:
                # Check it's not a retailer
                retailers = ["amazon", "walmart", "chewy", "petco", "petsmart", "target"]
                if not any(r in url for r in retailers):
                    return result["url"]

        # Return first result as fallback
        return search_results[0]["url"]

    async def _extract_product_data(
        self,
        url: str,
        sku: str,
        product_name: Optional[str],
        brand: Optional[str],
    ) -> dict[str, Any]:
        """Extract product data from the selected URL using browser-use."""
        browser = None
        try:
            import os

            browser_module = __import__("browser_use", fromlist=["Browser", "Agent"])
            Browser = getattr(browser_module, "Browser")
            Agent = getattr(browser_module, "Agent")
            browser_llm_module = __import__("browser_use.llm", fromlist=["ChatOpenAI"])
            ChatOpenAI = getattr(browser_llm_module, "ChatOpenAI")

            # Initialize browser
            browser = Browser(headless=self.headless)

            # Initialize LLM
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                return {"success": False, "error": "OPENAI_API_KEY not set"}

            llm = ChatOpenAI(
                model=self.llm_model,
                api_key=api_key,
                temperature=0,
            )

            # Build extraction task
            task = f"""Navigate to {url} and extract product information for:
SKU: {sku}
Expected Brand: {brand or "Unknown"}
Expected Product: {product_name or "Unknown"}

Extract the following fields:
- product_name: The exact product name
- brand: The brand name (verify it matches expected brand if provided)
- price: Current price (with currency symbol)
- description: Full product description
- images: List of product image URLs
- availability: In stock status

Return ONLY a JSON object with these fields. If a field is not available, use null."""

            # Create and run agent
            agent = Agent(
                task=task,
                llm=llm,
                browser=browser,
                max_steps=self.max_steps,
            )

            result = await agent.run()

            # Parse result
            result_text = result.content if hasattr(result, "content") else str(result)

            # Extract JSON from result
            try:
                # Find JSON in the response
                start = result_text.find("{")
                end = result_text.rfind("}")
                if start >= 0 and end > start:
                    json_str = result_text[start : end + 1]
                    data = json.loads(json_str)
                else:
                    data = {}

                # Validate and enhance result
                data["success"] = True
                data["url"] = url

                # Calculate confidence based on filled fields
                required_fields = ["product_name", "brand", "price", "images"]
                filled = sum(1 for f in required_fields if data.get(f))
                data["confidence"] = filled / len(required_fields)

                return data

            except json.JSONDecodeError:
                return {
                    "success": False,
                    "error": "Could not parse extraction result",
                    "raw_response": result_text[:500],
                }

        except Exception as e:
            logger.error(f"[AI Discovery] Extraction failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }
        finally:
            # Cleanup browser
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass


# Convenience function for direct usage
async def scrape_product(sku: str, product_name: Optional[str] = None, brand: Optional[str] = None, **kwargs) -> DiscoveryResult:
    """Scrape a product using AI discovery.

    Convenience function that creates a scraper instance and runs extraction.

    Args:
        sku: Product SKU
        product_name: Product name
        brand: Product brand
        **kwargs: Additional options for AIDiscoveryScraper

    Returns:
        DiscoveryResult
    """
    scraper = AIDiscoveryScraper(**kwargs)
    return await scraper.scrape_product(sku, product_name, brand)
