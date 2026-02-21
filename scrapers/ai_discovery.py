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
import re
import importlib
import os
import html as html_module
from typing import Any, Optional
from dataclasses import dataclass
from urllib.parse import urlparse, urljoin
from collections import OrderedDict
from difflib import SequenceMatcher

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
        self.use_ai_source_selection = os.getenv("AI_DISCOVERY_USE_LLM_SOURCE_RANKING", "false").lower() == "true"
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
            search_query = self._build_search_query(sku, product_name, brand, category)
            logger.info(f"[AI Discovery] Searching for: {search_query}")

            # Step 2: Search for product pages
            search_results: list[dict[str, Any]] = []
            search_error: Optional[str] = None
            best_score_seen = float("-inf")
            for query_variant in self._build_query_variants(
                sku=sku,
                product_name=product_name,
                brand=brand,
                category=category,
            ):
                raw_results, raw_error = await self._search_product(query_variant)
                prepared_results = self._prepare_search_results(raw_results, sku, brand, product_name, category)
                if prepared_results:
                    top_score = self._score_search_result(
                        result=prepared_results[0],
                        sku=sku,
                        brand=brand,
                        product_name=product_name,
                        category=category,
                    )
                    if top_score > best_score_seen:
                        best_score_seen = top_score
                        search_results = prepared_results
                        search_error = None
                    if top_score >= 8.0:
                        break
                search_error = raw_error

            if not search_results:
                error_msg = search_error or "No search results found"
                return DiscoveryResult(success=False, sku=sku, error=error_msg)

            # Step 3-5: Try extracting from each source with fallback
            max_attempts = 3
            extraction_result: Optional[dict[str, Any]] = None
            accepted_result: Optional[dict[str, Any]] = None
            last_rejection_reason: Optional[str] = None
            target_url = None
            tried_urls: set[str] = set()

            for attempt in range(max_attempts):
                if attempt == 0:
                    target_url = self._pick_strong_candidate_url(
                        search_results=search_results,
                        sku=sku,
                        brand=brand,
                        product_name=product_name,
                        category=category,
                    )
                    if not target_url:
                        if self.use_ai_source_selection:
                            target_url = await self._identify_best_source(search_results, sku, brand, product_name)
                        else:
                            target_url = self._heuristic_source_selection(search_results, brand)
                else:
                    target_url = str(search_results[0].get("url") or "")

                if not target_url or target_url in tried_urls:
                    if attempt < max_attempts - 1:
                        search_results = [r for r in search_results if r.get("url") != target_url]
                        continue
                    return DiscoveryResult(success=False, sku=sku, error="Could not identify suitable product page")

                logger.info(f"[AI Discovery] Selected source (attempt {attempt + 1}): {target_url}")

                selected_result = next((result for result in search_results if result.get("url") == target_url), None)
                if selected_result and self._is_low_quality_result(selected_result):
                    last_rejection_reason = "Selected source appears to be a non-product/review/aggregator page"
                    logger.info(f"[AI Discovery] Attempt {attempt + 1} rejected source before extraction: {target_url} ({last_rejection_reason})")
                    search_results = [r for r in search_results if r.get("url") != target_url]
                    if not search_results:
                        logger.warning("[AI Discovery] No more search results to try")
                        break
                    continue

                tried_urls.add(target_url)

                # Step 4: Extract product data from the selected page
                extraction_result = await self._extract_product_data(target_url, sku, product_name, brand)

                is_acceptable, rejection_reason = self._validate_extraction_match(
                    extraction_result=extraction_result,
                    sku=sku,
                    product_name=product_name,
                    brand=brand,
                    source_url=target_url,
                )
                if is_acceptable:
                    accepted_result = extraction_result
                    break

                last_rejection_reason = rejection_reason
                logger.info(f"[AI Discovery] Attempt {attempt + 1} rejected extracted data from {target_url}: {rejection_reason}. Trying next source...")

                # Remove tried URL from results and try next
                search_results = [r for r in search_results if r.get("url") != target_url]
                if not search_results:
                    logger.warning("[AI Discovery] No more search results to try")
                    break

            if not accepted_result:
                if extraction_result and extraction_result.get("error"):
                    error_msg = str(extraction_result.get("error"))
                elif last_rejection_reason:
                    error_msg = f"All extraction attempts rejected: {last_rejection_reason}"
                else:
                    error_msg = "All extraction attempts failed"
                return DiscoveryResult(success=False, sku=sku, error=error_msg)

            # Step 5: Record metrics
            cost_summary = self._cost_tracker.get_cost_summary()
            record_ai_extraction(
                scraper_name=f"ai_discovery_{brand or 'unknown'}",
                success=bool(accepted_result.get("success", False)),
                cost_usd=cost_summary.get("total_cost_usd", 0),
                duration_seconds=0.0,
                anti_bot_detected=bool(accepted_result.get("anti_bot_detected", False)),
            )

            # Build result
            if accepted_result.get("success"):
                return DiscoveryResult(
                    success=True,
                    sku=sku,
                    product_name=accepted_result.get("product_name") or product_name,
                    brand=accepted_result.get("brand") or brand,
                    description=accepted_result.get("description"),
                    size_metrics=accepted_result.get("size_metrics"),
                    images=accepted_result.get("images", []),
                    categories=accepted_result.get("categories", []),
                    url=target_url,
                    source_website=str(urlparse(target_url).netloc),
                    confidence=float(accepted_result.get("confidence", 0) or 0),
                    cost_usd=cost_summary.get("total_cost_usd", 0),
                )
            else:
                return DiscoveryResult(
                    success=False,
                    sku=sku,
                    error=str(accepted_result.get("error", "Extraction failed")),
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
        category: Optional[str] = None,
    ) -> str:
        """Build an effective search query for the product."""
        sku_clean = str(sku or "").strip()
        name_clean = str(product_name or "").strip()
        brand_clean = str(brand or "").strip()
        category_clean = str(category or "").strip()

        query_tokens: list[str] = []
        if brand_clean:
            query_tokens.append(brand_clean)
        if name_clean:
            query_tokens.append(name_clean)
        if sku_clean:
            query_tokens.append(sku_clean)
        if category_clean:
            query_tokens.append(category_clean)

        query_tokens.extend(
            [
                "product",
                "details",
                "-review",
                "-comparison",
                "-reddit",
                "-youtube",
                "-pinterest",
                "-coupon",
            ]
        )

        enable_brand_site_bias = os.getenv("BRAVE_BRAND_SITE_BIAS", "false").lower() == "true"
        if brand_clean and enable_brand_site_bias:
            query_tokens.append(f"site:{brand_clean.split()[0].lower()}.com")

        return " ".join(token for token in query_tokens if token)

    def _build_query_variants(
        self,
        sku: str,
        product_name: Optional[str],
        brand: Optional[str],
        category: Optional[str],
    ) -> list[str]:
        brand_clean = str(brand or "").strip()
        name_clean = str(product_name or "").strip()
        sku_clean = str(sku or "").strip()
        category_clean = str(category or "").strip()

        variants: list[str] = [self._build_search_query(sku_clean, name_clean, brand_clean, category_clean)]
        variants.append(" ".join(token for token in [brand_clean, name_clean, sku_clean, category_clean, "product"] if token))
        variants.append(" ".join(token for token in [brand_clean, name_clean, sku_clean] if token))
        variants.append(" ".join(token for token in [name_clean, sku_clean, "product"] if token))
        variants.append(" ".join(token for token in [brand_clean, name_clean, "product page"] if token))
        variants.append(" ".join(token for token in [sku_clean, "product"] if token))

        deduped_variants: list[str] = []
        seen: set[str] = set()
        for variant in variants:
            normalized = " ".join(variant.split())
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped_variants.append(normalized)
        return deduped_variants

    def _domain_from_url(self, value: str) -> str:
        domain = str(urlparse(value).netloc or "").lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    def _is_trusted_retailer(self, domain: str) -> bool:
        trusted = {
            "amazon.com",
            "walmart.com",
            "target.com",
            "chewy.com",
            "petco.com",
            "petsmart.com",
            "tractorsupply.com",
            "homedepot.com",
            "lowes.com",
            "acehardware.com",
            "berings.com",
            "farmstore.com",
            "hugglepets.co.uk",
            "mickeyspetsupplies.com",
            "rachelspetsupply.com",
            "animalproductsshop.com",
        }
        return any(domain == candidate or domain.endswith(f".{candidate}") for candidate in trusted)

    def _is_brand_domain(self, domain: str, brand: Optional[str]) -> bool:
        brand_normalized = self._normalize_token_text(brand)
        domain_normalized = self._normalize_token_text(domain)
        if not brand_normalized or not domain_normalized:
            return False
        return brand_normalized in domain_normalized

    def _is_category_like_url(self, url: str) -> bool:
        lowered = url.lower()
        category_like_patterns = [
            "/collections/",
            "/category/",
            "/categories/",
            "/shop/",
            "/search",
            "/products?",
            "/collections?",
        ]
        return any(pattern in lowered for pattern in category_like_patterns)

    def _normalize_token_text(self, value: Optional[str]) -> str:
        text = (value or "").lower()
        return re.sub(r"[^a-z0-9]", "", text)

    def _tokenize_keywords(self, value: Optional[str]) -> set[str]:
        stop_words = {
            "the",
            "and",
            "for",
            "with",
            "from",
            "that",
            "this",
            "your",
            "size",
            "pack",
            "inch",
            "inches",
            "oz",
            "lb",
            "lbs",
        }
        tokens = re.findall(r"[a-z0-9]+", (value or "").lower())
        return {token for token in tokens if len(token) >= 3 and token not in stop_words}

    def _is_low_quality_result(self, result: dict[str, Any]) -> bool:
        url = str(result.get("url") or "").lower()
        title = str(result.get("title") or "").lower()
        description = str(result.get("description") or "").lower()
        extra_snippets = " ".join(str(value) for value in (result.get("extra_snippets") or []))
        combined = f"{title} {description} {extra_snippets} {url}"

        low_quality_terms = [
            "review",
            "best",
            "top 10",
            "comparison",
            "vs",
            "reddit",
            "pinterest",
            "youtube",
            "facebook",
            "instagram",
            "tiktok",
            "affiliate",
            "coupon",
            "deal",
            "blog",
            "forum",
            "category/",
            "/collections/",
            "gift guide",
            "buying guide",
            "top picks",
            "best toys",
            "best dog toys",
        ]

        domain = self._domain_from_url(url)
        blocked_domains = {
            "reddit.com",
            "pinterest.com",
            "youtube.com",
            "facebook.com",
            "instagram.com",
            "tiktok.com",
            "medium.com",
            "quora.com",
        }
        if domain and any(domain == blocked or domain.endswith(f".{blocked}") for blocked in blocked_domains):
            return True

        if self._is_category_like_url(url):
            return True

        return any(term in combined for term in low_quality_terms)

    def _score_search_result(
        self,
        result: dict[str, Any],
        sku: str,
        brand: Optional[str],
        product_name: Optional[str],
        category: Optional[str],
    ) -> float:
        url = str(result.get("url") or "")
        title = str(result.get("title") or "")
        description = str(result.get("description") or "")
        extra_snippets = " ".join(str(value) for value in (result.get("extra_snippets") or []))
        combined = f"{url} {title} {description} {extra_snippets}".lower()
        domain = self._domain_from_url(url)

        score = 0.0

        if sku and sku.lower() in combined:
            score += 5.0

        brand_tokens = self._tokenize_keywords(brand)
        if brand_tokens:
            score += min(3.0, float(sum(1 for token in brand_tokens if token in combined)))

        expected_tokens = self._tokenize_keywords(product_name)
        if expected_tokens:
            overlap = len(expected_tokens.intersection(self._tokenize_keywords(combined)))
            score += min(4.0, float(overlap) * 0.8)

        category_tokens = self._tokenize_keywords(category)
        if category_tokens:
            score += min(1.5, float(sum(1 for token in category_tokens if token in combined)) * 0.5)

        if any(marker in combined for marker in ["/product", "/products", "/p/", "-p-"]):
            score += 1.0

        if domain and brand and self._normalize_token_text(brand) in self._normalize_token_text(domain):
            score += 4.0

        if self._is_trusted_retailer(domain):
            score += 1.5

        if self._is_category_like_url(url):
            score -= 2.0

        if not self._is_category_like_url(url) and any(marker in combined for marker in ["price", "$", "in stock", "add to cart", "buy now"]):
            score += 1.0

        if self._is_low_quality_result(result):
            score -= 6.0

        return score

    def _pick_strong_candidate_url(
        self,
        search_results: list[dict[str, Any]],
        sku: str,
        brand: Optional[str],
        product_name: Optional[str],
        category: Optional[str],
    ) -> Optional[str]:
        if not search_results:
            return None

        scored: list[tuple[dict[str, Any], float]] = []
        for result in search_results:
            score = self._score_search_result(
                result=result,
                sku=sku,
                brand=brand,
                product_name=product_name,
                category=category,
            )
            scored.append((result, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        top_result, top_score = scored[0]
        second_score = scored[1][1] if len(scored) > 1 else -999.0

        if top_score >= 6.0 and (top_score - second_score) >= 2.0:
            return str(top_result.get("url") or "")

        return None

    def _prepare_search_results(
        self,
        search_results: list[dict[str, Any]],
        sku: str,
        brand: Optional[str],
        product_name: Optional[str],
        category: Optional[str],
    ) -> list[dict[str, Any]]:
        if not search_results:
            return []

        deduped: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for result in search_results:
            url = str(result.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            deduped.append(result)

        ranked = sorted(
            deduped,
            key=lambda result: self._score_search_result(result, sku, brand, product_name, category),
            reverse=True,
        )

        if brand:
            preferred = []
            for result in ranked:
                domain = self._domain_from_url(str(result.get("url") or ""))
                if self._is_trusted_retailer(domain) or self._is_brand_domain(domain, brand):
                    preferred.append(result)
            if preferred:
                ranked = preferred

        high_signal = [result for result in ranked if not self._is_low_quality_result(result)]
        return high_signal or ranked

    def _is_brand_match(self, expected_brand: Optional[str], actual_brand: Optional[str], source_url: str) -> bool:
        if not expected_brand:
            return True

        expected_normalized = self._normalize_token_text(expected_brand)
        if not expected_normalized:
            return True

        actual_normalized = self._normalize_token_text(actual_brand)
        if actual_normalized and (expected_normalized in actual_normalized or actual_normalized in expected_normalized):
            return True

        source_domain = self._normalize_token_text(urlparse(source_url).netloc)
        if source_domain and expected_normalized in source_domain:
            return True

        return False

    def _is_name_match(self, expected_name: Optional[str], actual_name: Optional[str]) -> bool:
        if not expected_name:
            return True
        if not actual_name:
            return False

        expected_normalized = self._normalize_token_text(expected_name)
        actual_normalized = self._normalize_token_text(actual_name)

        if expected_normalized and actual_normalized and (expected_normalized in actual_normalized or actual_normalized in expected_normalized):
            return True

        expected_tokens = self._tokenize_keywords(expected_name)
        actual_tokens = self._tokenize_keywords(actual_name)
        if not expected_tokens or not actual_tokens:
            return False

        token_overlap = len(expected_tokens.intersection(actual_tokens)) / max(1, len(expected_tokens))
        ratio = SequenceMatcher(None, expected_normalized, actual_normalized).ratio()

        return token_overlap >= 0.35 or ratio >= 0.6

    def _has_specific_token_overlap(
        self,
        expected_name: Optional[str],
        actual_name: Optional[str],
        brand: Optional[str],
    ) -> bool:
        expected_tokens = self._tokenize_keywords(expected_name)
        actual_tokens = self._tokenize_keywords(actual_name)
        brand_tokens = self._tokenize_keywords(brand)

        specific_expected = expected_tokens.difference(brand_tokens)
        if not specific_expected:
            return True

        return len(specific_expected.intersection(actual_tokens)) > 0

    def _validate_extraction_match(
        self,
        extraction_result: dict[str, Any],
        sku: str,
        product_name: Optional[str],
        brand: Optional[str],
        source_url: str,
    ) -> tuple[bool, str]:
        if not extraction_result.get("success"):
            return False, str(extraction_result.get("error") or "Extraction failed")

        images = extraction_result.get("images")
        if not isinstance(images, list) or len(images) == 0:
            return False, "Missing product images"

        raw_confidence = extraction_result.get("confidence", 0)
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            confidence = 0.0

        if confidence < self.confidence_threshold:
            return (
                False,
                f"Confidence below threshold ({confidence:.2f} < {self.confidence_threshold:.2f})",
            )

        minimum_domain_confidence = max(self.confidence_threshold, 0.76)
        source_domain = self._domain_from_url(source_url)
        is_trusted_domain = bool(source_domain) and (
            self._is_trusted_retailer(source_domain) or (bool(brand) and self._normalize_token_text(str(brand)) in self._normalize_token_text(source_domain))
        )
        if confidence + 0.005 < minimum_domain_confidence and not is_trusted_domain:
            return (
                False,
                f"Confidence too low for untrusted domain ({confidence:.2f} < {minimum_domain_confidence:.2f})",
            )

        source_domain_normalized = self._normalize_token_text(source_domain)
        extracted_name = str(extraction_result.get("product_name") or "").strip()
        if brand and source_domain_normalized and self._normalize_token_text(str(brand)) in source_domain_normalized:
            brand_in_name = self._normalize_token_text(str(brand)) in self._normalize_token_text(extracted_name)
            if not brand_in_name:
                return False, "Source domain brand does not match extracted product title"

        extracted_brand = str(extraction_result.get("brand") or "").strip()
        if not self._is_brand_match(brand, extracted_brand, source_url):
            return False, "Brand mismatch with expected product context"

        if product_name and not self._is_name_match(product_name, extracted_name):
            return False, "Product name mismatch with expected product context"

        if product_name and brand and not self._has_specific_token_overlap(product_name, extracted_name, brand):
            if source_domain and self._is_trusted_retailer(source_domain):
                return True, "ok"
            return False, "Product title missing specific expected variant tokens"

        if sku and not product_name and not brand:
            combined = (
                f"{source_url} {extracted_name} {extracted_brand} {extraction_result.get('description') or ''} {extraction_result.get('size_metrics') or ''}"
            ).lower()
            if sku.lower() not in combined:
                return False, "SKU not found in extracted product context"

        return True, "ok"

    def _extract_size_metrics(self, text: str) -> Optional[str]:
        normalized = " ".join((text or "").split())
        patterns = [
            r"\b\d+(?:\.\d+)?\s?(?:lb|lbs|pound|pounds)\b",
            r"\b\d+(?:\.\d+)?\s?(?:oz|ounce|ounces)\b",
            r"\b\d+(?:\.\d+)?\s?(?:kg|kilogram|kilograms|g|gram|grams)\b",
            r"\b\d+(?:\.\d+)?\s?(?:qt|quart|quarts|gal|gallon|gallons|ml|l|liter|liters)\b",
            r"\b\d+\s?(?:pack|pk|ct|count)\b",
            r"\b\d+(?:\.\d+)?\s?(?:in|inch|inches|cm|mm)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    def _normalize_images(self, images: list[str], source_url: str) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        source_domain = self._domain_from_url(source_url)
        for raw in images:
            value = str(raw or "").strip()
            if not value:
                continue
            absolute = urljoin(source_url, value)
            parsed = urlparse(absolute)
            if parsed.scheme not in {"http", "https"}:
                continue
            if source_domain and self._domain_from_url(absolute) != source_domain:
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            normalized.append(absolute)
        return normalized

    def _coerce_string_list(self, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            output: list[str] = []
            for item in value:
                if isinstance(item, str):
                    output.append(item)
            return output
        return []

    def _extract_product_from_html_jsonld(
        self,
        html_text: str,
        source_url: str,
        sku: str,
        product_name: Optional[str],
        brand: Optional[str],
    ) -> Optional[dict[str, Any]]:
        script_matches = re.findall(
            r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
            html_text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        candidates: list[dict[str, Any]] = []
        for block in script_matches:
            content = html_module.unescape(block).strip()
            if not content:
                continue
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                continue

            queue: list[Any] = [parsed]
            while queue:
                current = queue.pop(0)
                if isinstance(current, list):
                    queue.extend(current)
                    continue
                if not isinstance(current, dict):
                    continue
                if "@graph" in current and isinstance(current["@graph"], list):
                    queue.extend(current["@graph"])

                node_type = current.get("@type")
                node_types = node_type if isinstance(node_type, list) else [node_type]
                normalized_types = {str(item).lower() for item in node_types if item}
                if "product" not in normalized_types:
                    continue

                name_value = str(current.get("name") or "").strip()
                brand_value_raw = current.get("brand")
                if isinstance(brand_value_raw, dict):
                    brand_value = str(brand_value_raw.get("name") or "").strip()
                else:
                    brand_value = str(brand_value_raw or "").strip()

                image_values = self._coerce_string_list(current.get("image"))
                normalized_images = self._normalize_images(image_values, source_url)
                if not normalized_images:
                    continue

                categories = self._coerce_string_list(current.get("category"))
                description_value = str(current.get("description") or "").strip()
                sku_value = str(current.get("sku") or current.get("mpn") or "").strip()

                score = 0.0
                if sku and sku.lower() in f"{sku_value} {description_value} {name_value}".lower():
                    score += 4.0
                if brand and self._is_brand_match(brand, brand_value, source_url):
                    score += 3.0
                if product_name and self._is_name_match(product_name, name_value):
                    score += 3.0
                if categories:
                    score += 1.0

                size_metrics = self._extract_size_metrics(f"{name_value} {description_value}")

                filled_fields = sum(1 for value in [name_value, brand_value or brand, description_value, size_metrics, normalized_images, categories] if value)
                confidence = max(0.55, min(0.98, (filled_fields / 6.0) + (score / 12.0)))

                candidates.append(
                    {
                        "success": True,
                        "product_name": name_value,
                        "brand": brand_value or brand,
                        "description": description_value,
                        "size_metrics": size_metrics,
                        "images": normalized_images,
                        "categories": categories,
                        "confidence": confidence,
                        "_score": score,
                    }
                )

        if not candidates:
            return None

        candidates.sort(key=lambda candidate: float(candidate.get("_score", 0)), reverse=True)
        best = dict(candidates[0])
        best.pop("_score", None)
        return best

    def _extract_meta_content(self, html_text: str, key: str, *, property_attr: bool = True) -> Optional[str]:
        attribute_name = "property" if property_attr else "name"
        pattern = rf"<meta[^>]+{attribute_name}=[\"']{re.escape(key)}[\"'][^>]+content=[\"']([^\"']+)[\"']"
        match = re.search(pattern, html_text, flags=re.IGNORECASE)
        if not match:
            return None
        return html_module.unescape(match.group(1)).strip()

    async def _extract_product_data_fallback(
        self,
        url: str,
        sku: str,
        product_name: Optional[str],
        brand: Optional[str],
    ) -> dict[str, Any]:
        try:
            import httpx

            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                html_text = response.text

            jsonld_result = self._extract_product_from_html_jsonld(
                html_text=html_text,
                source_url=str(response.url),
                sku=sku,
                product_name=product_name,
                brand=brand,
            )
            if jsonld_result:
                jsonld_result["url"] = str(response.url)
                return jsonld_result

            title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
            title_text = html_module.unescape(title_match.group(1)).strip() if title_match else ""
            og_title = self._extract_meta_content(html_text, "og:title", property_attr=True) or ""
            og_description = self._extract_meta_content(html_text, "og:description", property_attr=True) or ""
            og_image = self._extract_meta_content(html_text, "og:image", property_attr=True) or ""

            images = self._normalize_images([og_image], str(response.url)) if og_image else []

            candidate_name = og_title or title_text
            if candidate_name and product_name and not self._is_name_match(product_name, candidate_name):
                return {
                    "success": False,
                    "error": "Fallback extraction title does not match expected product",
                }

            if brand and candidate_name and not self._is_brand_match(brand, candidate_name, str(response.url)):
                return {
                    "success": False,
                    "error": "Fallback extraction brand/domain does not match expected context",
                }

            if not candidate_name or not images:
                return {
                    "success": False,
                    "error": "Fallback extraction found no structured product data",
                }

            fallback_description = og_description or title_text
            fallback_size = self._extract_size_metrics(f"{candidate_name} {fallback_description}")
            confidence = 0.58
            if product_name and self._is_name_match(product_name, candidate_name):
                confidence += 0.1
            if brand and self._is_brand_match(brand, candidate_name, str(response.url)):
                confidence += 0.1
            confidence = min(confidence, 0.78)

            return {
                "success": True,
                "product_name": candidate_name,
                "brand": brand,
                "description": fallback_description,
                "size_metrics": fallback_size,
                "images": images,
                "categories": [category for category in ["Product"] if category],
                "confidence": confidence,
                "url": str(response.url),
            }

        except Exception as error:
            return {
                "success": False,
                "error": f"Fallback extraction failed: {error}",
            }

    async def _search_product(self, query: str) -> tuple[list[dict[str, Any]], Optional[str]]:
        """Search for product using Brave Search API.

        Args:
            query: Search query

        Returns:
            Tuple of (List of search results, Error message if any)
        """
        cached = self._cache_get(query)
        if cached is not None:
            return cached, None

        try:
            import httpx

            api_key = os.environ.get("BRAVE_API_KEY")
            if not api_key:
                logger.error("BRAVE_API_KEY not set")
                return [], "BRAVE_API_KEY not set"

            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            }
            country = os.environ.get("BRAVE_COUNTRY", "US")
            search_lang = os.environ.get("BRAVE_SEARCH_LANG", "en")
            params = {
                "q": query,
                "count": self.max_search_results,
                "country": country,
                "search_lang": search_lang,
                "ui_lang": f"{search_lang}-{country}",
                "safesearch": "moderate",
                "extra_snippets": "true",
                "freshness": os.environ.get("BRAVE_FRESHNESS", "py"),
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
                            "extra_snippets": result.get("extra_snippets", []),
                        }
                    )

            self._cache_set(query, search_results)
            return search_results, None

        except Exception as e:
            logger.error(f"[AI Discovery] Search failed: {e}")
            return [], str(e)

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
- NEVER select category pages, listicles, review roundups, or social/video pages when any PDP is available.
- A valid candidate should usually include product-level URL patterns (/product, /products, /p/) or explicit PDP cues in title/snippet.
- If all results are low quality or likely non-PDP, return 0.

OUTPUT FORMAT (STRICT)
- Return ONLY one integer from 1 to {len(search_results[: self.max_search_results])} for the best result.
- Return 0 only if none are suitable product pages."""

            response = await llm.ainvoke(prompt)
            response_text = response.content if hasattr(response, "content") else str(response)

            try:
                match = re.search(r"-?\d+", response_text)
                selection = int(match.group(0)) if match else 0
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

        scored = sorted(
            search_results,
            key=lambda result: self._score_search_result(result, "", brand, None, None),
            reverse=True,
        )

        for result in scored:
            if not self._is_low_quality_result(result):
                return str(result.get("url") or "")

        return str(scored[0].get("url") or "")

    async def _extract_product_data(
        self,
        url: str,
        sku: str,
        product_name: Optional[str],
        brand: Optional[str],
    ) -> dict[str, Any]:
        """Extract product data from the selected URL using crawl4ai."""
        try:
            from pydantic import BaseModel, Field

            try:
                crawl4ai_module = importlib.import_module("crawl4ai")
                extraction_module = importlib.import_module("crawl4ai.extraction_strategy")
            except ModuleNotFoundError:
                return await self._extract_product_data_fallback(
                    url=url,
                    sku=sku,
                    product_name=product_name,
                    brand=brand,
                )

            AsyncWebCrawler = getattr(crawl4ai_module, "AsyncWebCrawler")
            BrowserConfig = getattr(crawl4ai_module, "BrowserConfig")
            CrawlerRunConfig = getattr(crawl4ai_module, "CrawlerRunConfig")
            CacheMode = getattr(crawl4ai_module, "CacheMode")
            LLMConfig = getattr(crawl4ai_module, "LLMConfig")
            LLMExtractionStrategy = getattr(extraction_module, "LLMExtractionStrategy")

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
                    if isinstance(result.extracted_content, str):
                        raw_content = result.extracted_content.strip()
                        if raw_content.startswith("[") and '"error"' in raw_content.lower() and "auth" in raw_content.lower():
                            return await self._extract_product_data_fallback(
                                url=url,
                                sku=sku,
                                product_name=product_name,
                                brand=brand,
                            )

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
