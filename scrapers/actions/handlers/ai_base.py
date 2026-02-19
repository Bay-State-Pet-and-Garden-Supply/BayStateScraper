"""
Base class for AI-powered action handlers.

Provides common functionality for browser-use integration,
cost tracking, and error handling.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import importlib
import inspect
from typing import Any, TYPE_CHECKING, cast

from scrapers.actions.base import BaseAction

if TYPE_CHECKING:
    from scrapers.context import ScraperContext


class BaseAIAction(BaseAction, ABC):
    """Base class for AI actions using browser-use.

    This class provides the foundation for all AI-powered scraping actions,
    integrating browser-use's Agent and Browser capabilities with the
    existing BayState scraper framework.

    Subclasses must implement the `execute` method and can optionally
    override `initialize_browser`, `initialize_llm`, and `cleanup`.

    Example:
        @ActionRegistry.register("ai_extract")
        class AIExtractAction(BaseAIAction):
            async def execute(self, params: dict[str, Any]) -> Any:
                await self.initialize_browser(headless=True)
                await self.initialize_llm(model="gpt-4o-mini")
                # ... AI extraction logic
                await self.cleanup()
    """

    def __init__(self, ctx: "ScraperContext") -> None:
        """Initialize the BaseAIAction.

        Args:
            ctx: The ScraperContext providing access to browser, config, and results.
        """
        super().__init__(ctx)
        self.browser: Any | None = None
        self.llm: Any | None = None
        self._cost_tracker: dict[str, Any] | None = None
        self._using_shared_ai_browser: bool = False

    async def initialize_browser(self, headless: bool = True) -> Any:
        """Initialize browser-use Browser instance.

        Creates a new Browser instance for AI agent interactions.
        The browser is stored in `self.browser` and should be cleaned
        up using `cleanup()` when done.

        Args:
            headless: Whether to run browser in headless mode. Defaults to True.

        Returns:
            The initialized Browser instance.

        Example:
            browser = await self.initialize_browser(headless=True)
        """
        existing_browser = getattr(self.ctx, "ai_browser", None)
        if existing_browser is not None:
            self.browser = existing_browser
            self._using_shared_ai_browser = True
            return self.browser

        browser_use_module = importlib.import_module("browser_use")
        browser_factory = cast(Any, getattr(browser_use_module, "Browser"))
        self.browser = browser_factory(headless=headless)
        self._using_shared_ai_browser = False
        return self.browser

    async def initialize_llm(self, model: str = "gpt-4o-mini", api_key: str | None = None, temperature: float = 0.0, **kwargs: Any) -> Any:
        """Initialize LLM with browser-use wrapper.

        Creates a ChatOpenAI instance configured for use with browser-use Agent.
        API key is resolved from params, ctx.config, ctx.results, or environment.

        Args:
            model: The OpenAI model to use. Defaults to "gpt-4o-mini".
            api_key: OpenAI API key. If None, attempts to resolve from context.
            temperature: Sampling temperature. Defaults to 0.0 for deterministic output.
            **kwargs: Additional arguments passed to ChatOpenAI.

        Returns:
            The initialized ChatOpenAI instance.

        Raises:
            ValueError: If no API key can be resolved.

        Example:
            llm = await self.initialize_llm(model="gpt-4o")
        """
        if api_key is None:
            # Try to resolve API key from context
            api_key = getattr(self.ctx.config, "openai_api_key", None) or self.ctx.results.get("openai_api_key") or self.ctx.context.get("openai_api_key")

        if not api_key:
            raise ValueError("OpenAI API key required. Provide via params, ctx.config.openai_api_key, ctx.results, or ctx.context")

        llm_module = importlib.import_module("browser_use.llm")
        chat_openai_factory = cast(Any, getattr(llm_module, "ChatOpenAI"))
        self.llm = chat_openai_factory(model=model, api_key=api_key, temperature=temperature, **kwargs)
        return self.llm

    def track_cost(self, input_tokens: int, output_tokens: int, model: str, cost_usd: float | None = None) -> None:
        """Track AI extraction cost. Hook for cost monitoring.

        This method provides a hook for cost tracking and monitoring.
        If the ScraperContext has a `track_ai_cost` method, it will be called
        with the token usage information. Additionally, costs are accumulated
        in `self._cost_tracker`.

        Args:
            input_tokens: Number of input tokens used.
            output_tokens: Number of output tokens generated.
            model: The model name used for the request.
            cost_usd: Optional pre-calculated cost in USD.

        Example:
            self.track_cost(input_tokens=150, output_tokens=50, model="gpt-4o-mini")
        """
        # Initialize cost tracker if needed
        if self._cost_tracker is None:
            self._cost_tracker = {
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_requests": 0,
                "models_used": set(),
                "estimated_cost_usd": 0.0,
            }

        # Update local tracker
        self._cost_tracker["total_input_tokens"] += input_tokens
        self._cost_tracker["total_output_tokens"] += output_tokens
        self._cost_tracker["total_requests"] += 1
        self._cost_tracker["models_used"].add(model)

        if cost_usd is not None:
            self._cost_tracker["estimated_cost_usd"] += cost_usd

        # Call context hook if available
        hook = getattr(self.ctx, "track_ai_cost", None)
        if callable(hook):
            try:
                hook(input_tokens=input_tokens, output_tokens=output_tokens, model=model, cost_usd=cost_usd)
            except Exception:
                # Silently ignore hook errors to not break execution
                pass

    def get_cost_summary(self) -> dict[str, Any]:
        """Get summary of tracked costs.

        Returns:
            Dictionary with cost tracking information.
        """
        if self._cost_tracker is None:
            return {
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_requests": 0,
                "models_used": [],
                "estimated_cost_usd": 0.0,
            }

        return {
            **self._cost_tracker,
            "models_used": list(self._cost_tracker["models_used"]),
        }

    @abstractmethod
    async def execute(self, params: dict[str, Any]) -> Any:
        """Execute AI action. Must be implemented by subclasses.

        This is the main entry point for AI-powered actions. Subclasses
        should implement their specific AI logic here, typically involving:
        1. Initialize browser and LLM
        2. Create and run browser-use Agent
        3. Process and return results
        4. Call cleanup()

        Args:
            params: Action parameters from YAML workflow.

        Returns:
            Result of the AI action execution.

        Raises:
            WorkflowExecutionError: If the action fails.
        """
        pass

    async def cleanup(self) -> None:
        """Cleanup browser resources.

        Closes the browser instance if it was initialized.
        This should be called in a finally block to ensure resources
        are released even if the action fails.

        Example:
            try:
                await self.execute(params)
            finally:
                await self.cleanup()
        """
        if self.browser:
            if self._using_shared_ai_browser:
                self.browser = None
                return

            try:
                close_result = self.browser.close()
                if inspect.isawaitable(close_result):
                    await close_result
            except Exception:
                # Ignore cleanup errors
                pass
            finally:
                self.browser = None

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - ensures cleanup."""
        await self.cleanup()
