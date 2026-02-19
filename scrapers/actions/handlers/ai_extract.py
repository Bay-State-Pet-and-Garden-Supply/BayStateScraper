from __future__ import annotations

import asyncio
import importlib
import json
import logging
import math
import os
import re
from collections.abc import Mapping
from types import ModuleType
from typing import ClassVar, Protocol, cast
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import override

from scrapers.actions.handlers.ai_base import BaseAIAction
from scrapers.actions.registry import ActionRegistry
from scrapers.ai_cost_tracker import AICostTracker
from scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


class ProductData(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow")

    product_name: str | None = Field(default=None)
    price: str | None = Field(default=None)
    brand: str | None = Field(default=None)
    description: str | None = Field(default=None)
    image_url: str | None = Field(default=None)
    availability: str | None = Field(default=None)
    sku: str | None = Field(default=None)


@ActionRegistry.register("ai_extract")
class AIExtractAction(BaseAIAction):
    ANTI_BOT_CIRCUIT_BREAKER_THRESHOLD: int = 3
    _domain_block_counts: dict[str, int] = {}
    _ai_cost_tracker: AICostTracker | None = None
    llm: object | None = None
    browser: object | None = None

    @override
    async def execute(self, params: dict[str, object]) -> dict[str, object] | list[dict[str, object]]:
        task = self._coerce_str(params.get("task"), "")
        if not task:
            raise WorkflowExecutionError("ai_extract action requires 'task' parameter")

        schema_model, schema_fields = self._resolve_schema_model(params.get("schema"))
        visit_top_n = self._coerce_int(params.get("visit_top_n", 1), default=1, min_value=1, max_value=10)
        max_steps = self._coerce_int(params.get("max_steps", 10), default=10, min_value=1, max_value=50)
        confidence_threshold = self._coerce_float(params.get("confidence_threshold", 0.35), default=0.35, min_value=0.0, max_value=1.0)
        use_vision = self._coerce_bool(params.get("use_vision", False), default=False)
        model_name = self._coerce_str(params.get("model"), "gpt-4o-mini") or "gpt-4o-mini"
        timeout_seconds = self._coerce_int(params.get("timeout_seconds", 120), default=120, min_value=30, max_value=600)

        urls = self._resolve_target_urls(params=params, visit_top_n=visit_top_n)
        if not urls:
            logger.warning("ai_extract found no target URLs; returning empty extraction result")
            self.ctx.results["ai_extract_results"] = []
            return []

        self._ai_cost_tracker = AICostTracker()
        llm, browser = self._initialize_runtime(model_name=model_name, headless=self._resolve_headless_mode(params))

        successful: list[dict[str, object]] = []
        low_confidence: list[dict[str, object]] = []
        failures: list[dict[str, str]] = []

        try:
            for url in urls:
                domain = self._extract_domain(url)
                if self._is_domain_circuit_open(domain):
                    logger.warning("Skipping URL due to anti-bot circuit breaker: %s", url)
                    failures.append({"url": url, "error": "anti_bot_circuit_breaker_open"})
                    continue

                try:
                    extraction, token_usage = await self._extract_from_url(
                        url=url,
                        task=task,
                        llm=llm,
                        browser=browser,
                        schema_model=schema_model,
                        schema_fields=schema_fields,
                        max_steps=max_steps,
                        timeout_seconds=timeout_seconds,
                        use_vision=use_vision,
                    )

                    confidence = self._calculate_confidence(extraction, schema_fields)
                    extraction["_confidence"] = confidence
                    extraction["_source_url"] = url

                    self._track_cost_usage(
                        model_name=model_name,
                        input_tokens=token_usage["input_tokens"],
                        output_tokens=token_usage["output_tokens"],
                    )

                    _ = self._domain_block_counts.pop(domain, None)

                    if confidence >= confidence_threshold:
                        successful.append(extraction)
                    else:
                        low_confidence.append(extraction)
                        logger.info(
                            "Low-confidence extraction for %s (%.3f < %.3f)",
                            url,
                            confidence,
                            confidence_threshold,
                        )
                except Exception as exc:
                    if self._looks_like_anti_bot(str(exc)):
                        self._record_domain_block(domain)

                    logger.warning("ai_extract failed for %s: %s", url, exc)
                    failures.append({"url": url, "error": str(exc)})

            if not successful and low_confidence:
                best_fallback = max(low_confidence, key=lambda item: self._as_float(item.get("_confidence"), 0.0))
                successful.append(best_fallback)

            self.ctx.results["ai_extract_results"] = successful
            self.ctx.results["ai_extract_failures"] = failures
            self.ctx.results["ai_extract_cost"] = self._ai_cost_tracker.get_cost_summary()

            if not successful:
                return []

            if len(successful) == 1:
                return successful[0]

            return successful
        finally:
            await self.cleanup()

    async def _extract_from_url(
        self,
        url: str,
        task: str,
        llm: object,
        browser: object,
        schema_model: type[BaseModel],
        schema_fields: set[str],
        max_steps: int,
        timeout_seconds: int,
        use_vision: bool,
    ) -> tuple[dict[str, object], dict[str, int]]:
        schema_json = schema_model.model_json_schema()
        extraction_task = (
            f"{task}\n\n"
            f"Target URL: {url}\n"
            "Navigate to the target URL and extract the requested data.\n"
            "Return only a JSON object matching the schema below.\n"
            "If a value is unknown, use null.\n\n"
            f"Schema:\n{json.dumps(schema_json, indent=2)}"
        )

        agent_kwargs: dict[str, object] = {
            "task": extraction_task,
            "llm": llm,
            "browser": browser,
            "max_steps": max_steps,
        }

        if use_vision:
            agent_kwargs["use_vision"] = True

        browser_use_module = importlib.import_module("browser_use")
        agent_cls = self._resolve_agent_factory(browser_use_module)

        try:
            agent = agent_cls(**agent_kwargs)
        except TypeError:
            _ = agent_kwargs.pop("use_vision", None)
            agent = agent_cls(**agent_kwargs)

        result = await asyncio.wait_for(agent.run(), timeout=timeout_seconds)
        result_text = self._extract_result_text(result)

        if self._looks_like_anti_bot(result_text):
            raise WorkflowExecutionError("anti-bot challenge detected during ai_extract")

        parsed_payload = self._parse_json_payload(result_text)
        normalized_payload = self._normalize_payload(parsed_payload, schema_fields)
        validated = schema_model.model_validate(normalized_payload)

        usage = self._extract_token_usage(result_text=result_text, prompt_text=extraction_task, result=result)
        return validated.model_dump(mode="json"), usage

    def _resolve_target_urls(self, params: dict[str, object], visit_top_n: int) -> list[str]:
        explicit_urls = params.get("urls")
        if isinstance(explicit_urls, list):
            explicit_url_values = cast(list[object], explicit_urls)
            cleaned: list[str] = []
            for raw_value in explicit_url_values:
                if isinstance(raw_value, str):
                    stripped = raw_value.strip()
                    if stripped:
                        cleaned.append(stripped)
            if cleaned:
                return cleaned[:visit_top_n]

        ai_search_results_raw = self._ctx_result("ai_search_results", [])
        ai_search_results = cast(list[object], ai_search_results_raw) if isinstance(ai_search_results_raw, list) else []
        if ai_search_results:
            urls: list[str] = []
            for item in ai_search_results:
                if isinstance(item, dict):
                    item_dict = cast(Mapping[str, object], item)
                    raw_url = item_dict.get("url")
                    if isinstance(raw_url, str) and raw_url.strip():
                        urls.append(raw_url.strip())
                if len(urls) >= visit_top_n:
                    break
            if urls:
                return urls

        url = params.get("url") or self._ctx_result("url")
        if isinstance(url, str) and url.strip():
            return [url.strip()]

        return []

    def _resolve_schema_model(self, schema_param: object) -> tuple[type[BaseModel], set[str]]:
        if schema_param is None:
            return ProductData, set(ProductData.model_fields.keys())

        if isinstance(schema_param, type) and issubclass(schema_param, BaseModel):
            return schema_param, set(schema_param.model_fields.keys())

        if isinstance(schema_param, str):
            schema_name = schema_param.strip()
            if not schema_name:
                return ProductData, set(ProductData.model_fields.keys())

            if schema_name == "ProductData":
                return ProductData, set(ProductData.model_fields.keys())

            try:
                parsed = self._json_loads_object(schema_name)
                if isinstance(parsed, dict):
                    return ProductData, self._extract_schema_fields(cast(dict[str, object], parsed))
            except json.JSONDecodeError:
                logger.warning("Unknown schema string '%s'; defaulting to ProductData", schema_name)
                return ProductData, set(ProductData.model_fields.keys())

        if isinstance(schema_param, dict):
            return ProductData, self._extract_schema_fields(cast(dict[str, object], schema_param))

        logger.warning("Unsupported schema param type for ai_extract; defaulting to ProductData")
        return ProductData, set(ProductData.model_fields.keys())

    def _extract_schema_fields(self, schema_dict: dict[str, object]) -> set[str]:
        properties_obj = schema_dict.get("properties", schema_dict)
        properties = cast(dict[object, object], properties_obj) if isinstance(properties_obj, dict) else None
        if properties is None or not properties:
            return set(ProductData.model_fields.keys())

        extracted = {key for key in properties.keys() if isinstance(key, str) and key}
        return extracted or set(ProductData.model_fields.keys())

    def _parse_json_payload(self, raw_text: str) -> dict[str, object]:
        candidate_blocks = self._extract_json_candidates(raw_text)

        for candidate in candidate_blocks:
            try:
                parsed = self._json_loads_object(candidate)
                if isinstance(parsed, dict):
                    return cast(dict[str, object], parsed)
                if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                    return cast(dict[str, object], parsed[0])
            except json.JSONDecodeError:
                continue

        raise WorkflowExecutionError("ai_extract could not parse structured JSON from agent output")

    def _extract_json_candidates(self, text: str) -> list[str]:
        candidates: list[str] = []

        fenced_blocks = re.findall(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
        candidates.extend(fenced_blocks)

        brace_matches = re.findall(r"\{[\s\S]*\}", text)
        candidates.extend(brace_matches)

        bracket_matches = re.findall(r"\[[\s\S]*\]", text)
        candidates.extend(bracket_matches)

        candidates.append(text)
        return [candidate.strip() for candidate in candidates if candidate and candidate.strip()]

    def _normalize_payload(self, payload: dict[str, object], expected_fields: set[str]) -> dict[str, object]:
        if not expected_fields:
            return payload

        normalized = {k: v for k, v in payload.items() if k in expected_fields}
        if normalized:
            return normalized
        return payload

    def _calculate_confidence(self, payload: dict[str, object], schema_fields: set[str]) -> float:
        if not payload:
            return 0.0

        explicit = payload.get("_confidence")
        if isinstance(explicit, (int, float)) and not math.isnan(float(explicit)):
            return self._clamp(float(explicit), 0.0, 1.0)

        fields = list(schema_fields)
        if not fields:
            return 0.5

        present = 0
        for field in fields:
            value = payload.get(field)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            present += 1

        completeness = present / max(len(fields), 1)
        return self._clamp(0.15 + (0.85 * completeness), 0.0, 1.0)

    def _extract_result_text(self, result: object) -> str:
        for method_name in ("final_result", "model_dump_json", "model_dump"):
            attr = self._safe_getattr(result, method_name)
            if callable(attr):
                try:
                    value = attr()
                    if isinstance(value, str) and value.strip():
                        return value
                    if isinstance(value, dict):
                        return json.dumps(value)
                except Exception:
                    continue

        for attr_name in ("result", "output", "final_output", "message"):
            value = self._safe_getattr(result, attr_name)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, dict):
                return json.dumps(value)

        return str(result)

    def _extract_token_usage(self, result_text: str, prompt_text: str, result: object) -> dict[str, int]:
        usage_candidates = [
            self._safe_getattr(result, "usage"),
            self._safe_getattr(result, "token_usage"),
            self._safe_getattr(result, "usage_metadata"),
        ]

        for candidate in usage_candidates:
            if isinstance(candidate, Mapping):
                usage_mapping = cast(Mapping[str, object], candidate)
                input_tokens = self._coerce_int(usage_mapping.get("input_tokens") or usage_mapping.get("prompt_tokens"), default=0)
                output_tokens = self._coerce_int(usage_mapping.get("output_tokens") or usage_mapping.get("completion_tokens"), default=0)
                if input_tokens > 0 or output_tokens > 0:
                    return {"input_tokens": input_tokens, "output_tokens": output_tokens}

        input_tokens = max(1, len(prompt_text) // 4)
        output_tokens = max(1, len(result_text) // 4)
        return {"input_tokens": input_tokens, "output_tokens": output_tokens}

    def _track_cost_usage(self, model_name: str, input_tokens: int, output_tokens: int) -> None:
        scraper_name = self._coerce_str(getattr(self.ctx.config, "name", None), "default") or "default"
        if self._ai_cost_tracker is None:
            self._ai_cost_tracker = AICostTracker()

        extraction_cost = self._ai_cost_tracker.track_extraction(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model_name,
            scraper_name=scraper_name,
        )

        self.track_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model_name,
            cost_usd=extraction_cost.cost_usd,
        )

    def _is_domain_circuit_open(self, domain: str) -> bool:
        if not domain:
            return False
        return self._domain_block_counts.get(domain, 0) >= self.ANTI_BOT_CIRCUIT_BREAKER_THRESHOLD

    def _record_domain_block(self, domain: str) -> None:
        if not domain:
            return
        strikes = self._domain_block_counts.get(domain, 0) + 1
        self._domain_block_counts[domain] = strikes
        logger.warning(
            "Anti-bot block recorded for domain '%s' (%s/%s)",
            domain,
            strikes,
            self.ANTI_BOT_CIRCUIT_BREAKER_THRESHOLD,
        )

    def _extract_domain(self, url: str) -> str:
        try:
            return urlparse(url).netloc.lower().removeprefix("www.")
        except Exception:
            return ""

    def _looks_like_anti_bot(self, value: str) -> bool:
        text = value.lower()
        indicators = (
            "captcha",
            "recaptcha",
            "hcaptcha",
            "press and hold",
            "verify you are human",
            "access denied",
            "forbidden",
            "unusual traffic",
            "challenge",
            "blocked",
        )
        return any(indicator in text for indicator in indicators)

    def _resolve_headless_mode(self, params: dict[str, object]) -> bool:
        if "headless" in params:
            return self._coerce_bool(params.get("headless"), default=True)

        env_value = os.getenv("HEADLESS", "true").strip().lower()
        return env_value not in {"false", "0", "no"}

    def _coerce_int(self, value: object, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
        try:
            if isinstance(value, bool):
                raise ValueError("bool not allowed")
            coerced = int(str(value).strip()) if value is not None else default
        except Exception:
            coerced = default

        if min_value is not None:
            coerced = max(min_value, coerced)
        if max_value is not None:
            coerced = min(max_value, coerced)
        return coerced

    def _coerce_float(self, value: object, default: float, min_value: float | None = None, max_value: float | None = None) -> float:
        try:
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ValueError("invalid float type")
            coerced = float(value)
            if math.isnan(coerced):
                raise ValueError("nan")
        except Exception:
            coerced = default

        if min_value is not None:
            coerced = max(min_value, coerced)
        if max_value is not None:
            coerced = min(max_value, coerced)
        return coerced

    def _coerce_bool(self, value: object, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y"}:
                return True
            if lowered in {"false", "0", "no", "n"}:
                return False
        return default

    def _coerce_str(self, value: object, default: str = "") -> str:
        if isinstance(value, str):
            return value
        return default

    def _clamp(self, value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))

    def _as_float(self, value: object, default: float) -> float:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except Exception:
                return default
        return default

    def _safe_getattr(self, instance: object, name: str) -> object | None:
        try:
            return cast(object, getattr(instance, name))
        except Exception:
            return None

    def _initialize_runtime(self, model_name: str, headless: bool) -> tuple[object, object]:
        browser_use_module = importlib.import_module("browser_use")
        llm_module = importlib.import_module("browser_use.llm")

        browser_factory = self._resolve_browser_factory(browser_use_module)
        chat_openai_factory = self._resolve_chat_openai_factory(llm_module)

        api_key = self._resolve_api_key()
        llm = chat_openai_factory(model=model_name, api_key=api_key, temperature=0.0)
        browser = browser_factory(headless=headless)

        self.llm = llm
        self.browser = browser
        return llm, browser

    def _resolve_api_key(self) -> str:
        key = getattr(self.ctx.config, "openai_api_key", None)
        if not isinstance(key, str) or not key.strip():
            result_key = self._ctx_result("openai_api_key")
            key = result_key if isinstance(result_key, str) else None
        if not isinstance(key, str) or not key.strip():
            context_key = cast(object, self.ctx.context.get("openai_api_key"))
            key = context_key if isinstance(context_key, str) else None
        if not isinstance(key, str) or not key.strip():
            env_key = os.getenv("OPENAI_API_KEY")
            key = env_key if isinstance(env_key, str) else None
        if not isinstance(key, str) or not key.strip():
            raise WorkflowExecutionError("OpenAI API key required for ai_extract")
        return key

    def _resolve_agent_factory(self, module: ModuleType) -> "AgentFactory":
        candidate_obj: object = getattr(module, "Agent", None)
        if candidate_obj is None or not callable(candidate_obj):
            raise WorkflowExecutionError("browser_use.Agent not available")
        return cast(AgentFactory, candidate_obj)

    def _resolve_browser_factory(self, module: ModuleType) -> "BrowserFactory":
        candidate_obj: object = getattr(module, "Browser", None)
        if candidate_obj is None or not callable(candidate_obj):
            raise WorkflowExecutionError("browser_use.Browser not available")
        return cast(BrowserFactory, candidate_obj)

    def _resolve_chat_openai_factory(self, module: ModuleType) -> "ChatOpenAIFactory":
        candidate_obj: object = getattr(module, "ChatOpenAI", None)
        if candidate_obj is None or not callable(candidate_obj):
            raise WorkflowExecutionError("browser_use.llm.ChatOpenAI not available")
        return cast(ChatOpenAIFactory, candidate_obj)

    def _ctx_result(self, key: str, default: object | None = None) -> object:
        return cast(object, self.ctx.results.get(key, default))

    def _json_loads_object(self, text: str) -> object:
        return cast(object, json.loads(text))


class AgentRunner(Protocol):
    async def run(self) -> object: ...


class AgentFactory(Protocol):
    def __call__(self, **kwargs: object) -> AgentRunner: ...


class BrowserFactory(Protocol):
    def __call__(self, **kwargs: object) -> object: ...


class ChatOpenAIFactory(Protocol):
    def __call__(self, **kwargs: object) -> object: ...
