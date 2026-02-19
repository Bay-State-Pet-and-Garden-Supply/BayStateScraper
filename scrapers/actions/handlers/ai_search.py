from __future__ import annotations

import asyncio
import logging
import os
from typing import Union, cast
from urllib.parse import urlparse

import httpx
from typing_extensions import override

from scrapers.actions.handlers.ai_base import BaseAIAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


SearchResult = dict[str, Union[str, int]]
SearchResultList = list[SearchResult]


@ActionRegistry.register("ai_search")
class AISearchAction(BaseAIAction):
    BRAVE_API_URL: str = "https://api.search.brave.com/res/v1/web/search"

    @override
    async def execute(self, params: dict[str, object]) -> SearchResultList:
        query_raw = params.get("query", "")
        query = query_raw.strip() if isinstance(query_raw, str) else ""
        if not query:
            raise WorkflowExecutionError("ai_search action requires 'query' parameter")

        max_results = self._coerce_max_results(params.get("max_results", 5))
        api_key = self._get_api_key()
        formatted_query = self._format_query(query)

        results = await self._search_brave(
            query=formatted_query,
            max_results=max_results,
            api_key=api_key,
        )
        scored_results = self._score_results(results=results, query=formatted_query)

        self.ctx.results["ai_search_results"] = scored_results
        return scored_results

    def _coerce_max_results(self, value: object) -> int:
        try:
            if isinstance(value, bool):
                raise ValueError("bool not allowed")
            if isinstance(value, int):
                max_results = value
            elif isinstance(value, float):
                max_results = int(value)
            elif isinstance(value, str):
                max_results = int(value.strip())
            else:
                raise ValueError("unsupported max_results type")
        except (TypeError, ValueError):
            max_results = 5

        return max(1, min(max_results, 20))

    def _get_api_key(self) -> str:
        api_key = getattr(self.ctx.config, "brave_api_key", None) or self.ctx.results.get("brave_api_key") or self.ctx.context.get("brave_api_key")

        if not api_key:
            api_key = os.getenv("BRAVE_SEARCH_API_KEY")

        if not isinstance(api_key, str) or not api_key.strip():
            raise WorkflowExecutionError("Brave Search API key required. Set BRAVE_SEARCH_API_KEY environment variable or provide via ctx.config.brave_api_key")

        return api_key

    def _format_query(self, query: str) -> str:
        merged_context: dict[str, object] = {
            "sku": self.ctx.results.get("sku", ""),
            "placeholder_name": self.ctx.results.get("placeholder_name", ""),
            **self.ctx.results,
            **self.ctx.context,
        }

        try:
            return query.format_map(SafeDict(merged_context)).strip()
        except (ValueError, KeyError):
            return query

    async def _search_brave(
        self,
        query: str,
        max_results: int,
        api_key: str,
        retries: int = 3,
        base_backoff_seconds: float = 1.0,
    ) -> SearchResultList:
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        }
        request_params = {
            "q": query,
            "count": max_results,
            "offset": 0,
        }

        for attempt in range(1, retries + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(
                        self.BRAVE_API_URL,
                        headers=headers,
                        params=request_params,
                    )
                    _ = response.raise_for_status()
                    payload_obj = self._parse_response_json(response)

                payload = cast(dict[str, object], payload_obj) if isinstance(payload_obj, dict) else {}
                web_section_obj = payload.get("web")
                web_obj = cast(dict[str, object], web_section_obj) if isinstance(web_section_obj, dict) else {}
                raw_results_obj = web_obj.get("results")
                web_results = cast(list[object], raw_results_obj) if isinstance(raw_results_obj, list) else []

                parsed_results: SearchResultList = []
                for item in web_results[:max_results]:
                    if not isinstance(item, dict):
                        continue
                    item_dict = cast(dict[str, object], item)
                    url = item_dict.get("url")
                    title = item_dict.get("title")
                    description = item_dict.get("description")
                    parsed_results.append(
                        {
                            "url": url if isinstance(url, str) else "",
                            "title": title if isinstance(title, str) else "",
                            "description": description if isinstance(description, str) else "",
                            "domain": self._extract_domain(url if isinstance(url, str) else ""),
                        }
                    )

                return parsed_results
            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.HTTPStatusError,
                httpx.DecodingError,
            ) as exc:
                is_last_attempt = attempt >= retries
                logger.warning(
                    "Brave Search request failed (attempt %s/%s): %s",
                    attempt,
                    retries,
                    exc,
                )
                if is_last_attempt:
                    raise WorkflowExecutionError(f"Brave Search API request failed after {retries} attempts: {exc}") from exc

                backoff = base_backoff_seconds * (2.0 ** (attempt - 1))
                await asyncio.sleep(backoff)

        return []

    def _score_results(
        self,
        results: SearchResultList,
        query: str,
    ) -> SearchResultList:
        sku = query.split()[0].strip().lower() if query else ""
        product_domains = ["amazon", "walmart", "target", "ebay", "bestbuy"]

        scored_results: SearchResultList = []
        for result in results:
            score = 0
            url = self._safe_lower(result.get("url"))
            title = self._safe_lower(result.get("title"))
            description = self._safe_lower(result.get("description"))
            domain = self._safe_lower(result.get("domain"))

            if sku:
                if sku in url:
                    score += 10
                if sku in title:
                    score += 5
                if sku in description:
                    score += 3

            if any(product_domain in domain for product_domain in product_domains):
                score += 2

            scored_results.append({**result, "score": score})

        scored_results.sort(
            key=lambda item: item["score"] if isinstance(item.get("score"), int) else -1,
            reverse=True,
        )
        return scored_results

    def _extract_domain(self, url: str) -> str:
        try:
            netloc = urlparse(url).netloc.lower()
            return netloc.removeprefix("www.")
        except Exception:
            return ""

    def _safe_lower(self, value: Union[str, int, None]) -> str:
        return value.lower() if isinstance(value, str) else ""

    def _parse_response_json(self, response: httpx.Response) -> object:
        return cast(object, response.json())


class SafeDict(dict[str, object]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
