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
from scrapers.ai_metrics import record_ai_extraction

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryResult:
    """Result from AI discovery scraping."""

    success: bool
    sku: str
    product_name: Optional[str] = None
    brand: Optional[str] = None
    description: Optional[str] = None
    size_metrics: Optional[str] = None
    images: Optional[list[str]] = None
    categories: Optional[list[str]] = None
    url: Optional[str] = None
    source_website: Optional[str] = None
    confidence: float = 0.0
    cost_usd: float = 0.0
    error: Optional[str] = None

    def __post_init__(self):
        if self.images is None:
            self.images = []
        if self.categories is None:
            self.categories = []


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

            # Step 3-5: Try extracting from each source with fallback
            max_attempts = 3
            extraction_result = None
            target_url = None

            for attempt in range(max_attempts):
                # Step 3: Use AI to identify best source (prefer manufacturer website)
                target_url = await self._identify_best_source(search_results, sku, brand, product_name)
                if not target_url:
                    if attempt < max_attempts - 1:
                        # Remove failed URL and try next
                        search_results = [r for r in search_results if r.get("url") != target_url]
                        continue
                    return DiscoveryResult(success=False, sku=sku, error="Could not identify suitable product page")

                logger.info(f"[AI Discovery] Selected source (attempt {attempt + 1}): {target_url}")

                # Step 4: Extract product data from the selected page
                extraction_result = await self._extract_product_data(target_url, sku, product_name, brand)

                # Check if extraction succeeded and has images/confidence
                if extraction_result.get("success"):
                    images = extraction_result.get("images", [])
                    confidence = extraction_result.get("confidence", 0)

                    if len(images) > 0 and confidence >= 0.8:
                        # Good result, break out of loop
                        break

                    logger.info(f"[AI Discovery] Attempt {attempt + 1} returned {len(images)} images, confidence {confidence}. Trying next source...")

                # Remove tried URL from results and try next
                search_results = [r for r in search_results if r.get("url") != target_url]
                if not search_results:
                    logger.warning("[AI Discovery] No more search results to try")
                    break

            if not extraction_result:
                return DiscoveryResult(success=False, sku=sku, error="All extraction attempts failed")

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
                    description=extraction_result.get("description"),
                    size_metrics=extraction_result.get("size_metrics"),
                    images=extraction_result.get("images", []),
                    categories=extraction_result.get("categories", []),
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
        sku: str,
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

            # Prompt v2 - Optimized for manufacturer site detection and exact variant extraction
            prompt = f"""You are ranking search results to select the single best product page for structured extraction.

INPUT PRODUCT CONTEXT
- SKU: {sku or "Unknown"}
- Brand (may be null): {brand or "Unknown"}
- Product Name: {product_name or "Unknown"}

SEARCH RESULTS
{results_text}

INSTRUCTIONS
1) Infer the likely canonical brand when Brand is Unknown by using Product Name tokens and search result titles/descriptions.
2) Score each result using this weighted rubric (0-100 total):
   - Domain authority & source tier (0-45)
     - 45: official manufacturer / official brand domain for inferred brand
     - 30: major trusted retailer PDP (Home Depot, Lowe's, Walmart, Target, Chewy, Tractor Supply, Ace)
     - 10: marketplace / affiliate / review / aggregator pages
   - SKU/variant relevance (0-30)
     - Explicit SKU match or exact variant tokens (size/color/form) in title/snippet/url
   - Content quality signals (0-25)
     - Strong signals: explicit price mention, stock/availability hint, product detail depth, image-rich PDP indicators
     - Penalize thin pages, category pages, blog/review pages, comparison pages, or "best X" roundups

REQUIRED DECISION POLICY
- Prefer manufacturer page if it is plausibly the exact SKU/variant.
- If no viable manufacturer result exists, choose best major retailer PDP.
- Affiliate/review/aggregator pages are last resort and should only be selected when nothing else is viable.

OUTPUT FORMAT (STRICT)
- Return ONLY one integer from 1 to {len(search_results[: self.max_search_results])} for the best result.
- Return 0 only if none are suitable product pages."""

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
        """Extract product data from the selected URL using crawl4ai."""
        try:
            import os
            import json
            from pydantic import BaseModel, Field
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode, LLMConfig
            from crawl4ai.extraction_strategy import LLMExtractionStrategy

            class ProductData(BaseModel):
                product_name: str = Field(description="The exact product name")
                brand: str = Field(description="The brand name")
                description: str = Field(description="Full product description")
                size_metrics: str = Field(description="Size, weight, volume, or dimensions (e.g., '5 lb bag', '12oz bottle')")
                images: list[str] = Field(description="List of product image URLs")
                categories: list[str] = Field(description="Product types, categories, or tags (e.g., ['Dog Food', 'Dry Food', 'Grain-Free'])")

            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                return {"success": False, "error": "OPENAI_API_KEY not set"}

            browser_config = BrowserConfig(
                headless=self.headless,
                viewport={"width": 1920, "height": 1080},
            )

            # Prompt v2 - Optimized for manufacturer site detection and exact variant extraction
            instruction = f"""Extract structured product data for a single SKU-locked product page.

TARGET CONTEXT
- SKU: {sku}
- Expected Brand (may be null): {brand or "Unknown"}
- Expected Product Name: {product_name or "Unknown"}

CRITICAL EXTRACTION RULES
1) SKU / VARIANT LOCK (FUZZY VALIDATION)
   - Ensure extracted product refers to the same variant as the target SKU context.
   - Match using fuzzy evidence across: SKU text, size/weight, color, flavor, form-factor terms.
   - Do NOT output data for a different variant from carousel/recommendations.

2) BRAND INFERENCE
   - If Expected Brand is Unknown/null, infer brand from the product title, breadcrumb, manufacturer field, or structured data.
   - Return the canonical brand string (not store name).

3) MUST-FILL CHECKLIST BEFORE FINAL OUTPUT
   - product_name: required
   - images: at least 1 required
   - brand, description, size_metrics, categories: strongly preferred
   - If a required field cannot be found, keep searching the same page context (JSON-LD, meta, visible PDP modules) before giving up.

4) SIZE METRICS EXTRACTION
   - Extract size, weight, volume, or dimensions (e.g., "5 lb bag", "12oz bottle", "24-pack")
   - Look in title, product specs, variant selectors, or packaging information

5) CATEGORIES EXTRACTION
   - Extract product types, categories, or tags (e.g., ["Dog Food", "Dry Food", "Grain-Free"])
   - Look in breadcrumbs, category navigation, product tags, or structured data

6) IMAGE PRIORITIZATION
     - images: Extract ALL high-resolution product image URLs from the image carousel, gallery thumbnails, and JSON-LD structured data blocks.
     - Look carefully for `data-src` attributes, `<script type="application/ld+json">`, and elements with classes like `carousel` or `gallery`.
     - Do not just grab the first image. Return absolute URLs only (https://...).
     - Put primary hero image first, then additional product angles, variants, and detail shots.
     - Exclude sprites, icons, logos, and unrelated recommendation images.
     - DO NOT HALLUCINATE OR INVENT URLS. If you cannot find absolute URLs on the current domain, return an empty list rather than `example.com` or placeholder URLs.

7) DESCRIPTION QUALITY
   - Extract meaningful product description/spec text for the exact variant, not generic category copy.

OUTPUT QUALITY BAR
- Return the most complete, variant-accurate record possible.
- Do not hallucinate missing values."""

            llm_strategy = LLMExtractionStrategy(
                llm_config=LLMConfig(
                    provider=f"openai/{self.llm_model}",
                    api_token=api_key,
                ),
                schema=ProductData.model_json_schema(),
                extraction_type="schema",
                instruction=instruction,
            )

            # JavaScript to scroll the page to trigger lazy loading of carousel images
            scroll_js = """
            async () => {
                // Scroll down to bottom to trigger lazy loading
                window.scrollTo(0, document.body.scrollHeight);
                await new Promise(resolve => setTimeout(resolve, 1000));
                
                // Scroll back up
                window.scrollTo(0, 0);
                await new Promise(resolve => setTimeout(resolve, 500));
                
                // Try to find and interact with carousel elements
                const carousels = document.querySelectorAll('[class*="carousel"], [class*="gallery"], [data-carousel], [role="carousel"]');
                for (const carousel of carousels) {
                    carousel.scrollLeft += 200;
                    await new Promise(resolve => setTimeout(resolve, 300));
                }
            }
            """

            crawl_config = CrawlerRunConfig(
                extraction_strategy=llm_strategy,
                cache_mode=CacheMode.BYPASS,
                js_code=scroll_js,
                delay_before_return_html=2.0,
                word_count_threshold=1,
            )

            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url=url, config=crawl_config)

                if result.success and result.extracted_content:
                    try:
                        data = json.loads(result.extracted_content)
                        if data and isinstance(data, list):
                            product_data = data[0]
                            product_data["success"] = True
                            product_data["url"] = url

                            # Calculate confidence based on filled fields
                            required_fields = ["product_name", "brand", "description", "size_metrics", "images", "categories"]
                            filled = sum(1 for f in required_fields if product_data.get(f))
                            product_data["confidence"] = filled / len(required_fields)

                            return product_data
                    except json.JSONDecodeError:
                        return {
                            "success": False,
                            "error": "Could not parse extraction result",
                            "raw_response": result.extracted_content[:500],
                        }
                return {
                    "success": False,
                    "error": result.error_message or "Extraction failed or returned no content",
                }

        except Exception as e:
            logger.error(f"[AI Discovery] Extraction failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }


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
