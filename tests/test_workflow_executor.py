from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from typing_extensions import override

from scrapers.actions.base import BaseAction

from scrapers.models.config import ScraperConfig, SelectorConfig, WorkflowStep


def _build_config(*, workflows: list[WorkflowStep] | None = None, selectors: list[SelectorConfig] | None = None) -> ScraperConfig:
    return ScraperConfig(
        schema_version="1.0",
        name="char-test-scraper",
        base_url="https://example.com",
        display_name=None,
        normalization=None,
        login=None,
        timeout=30,
        retries=2,
        anti_detection=None,
        http_status=None,
        validation=None,
        test_skus=None,
        fake_skus=None,
        edge_case_skus=None,
        image_quality=50,
        selectors=selectors or [],
        workflows=workflows or [],
    )


def _build_agentic_config(*, workflows: list[WorkflowStep] | None = None) -> ScraperConfig:
    return ScraperConfig(
        schema_version="1.0",
        name="agentic-test-scraper",
        base_url="https://example.com",
        display_name=None,
        scraper_type="agentic",
        normalization=None,
        login=None,
        timeout=30,
        retries=2,
        anti_detection=None,
        http_status=None,
        validation=None,
        test_skus=None,
        fake_skus=None,
        edge_case_skus=None,
        image_quality=50,
        selectors=[],
        workflows=workflows or [],
    )


class _DummyBrowser:
    def __init__(self, page: _DummyPage | None = None) -> None:
        self.page: _DummyPage | None = page

    def quit(self) -> None:
        return None


class _DummyElement:
    async def inner_text(self) -> str:
        return "$10.99"

    async def text_content(self) -> str:
        return "$10.99"

    async def get_attribute(self, _attribute: str) -> str | None:
        return None


class _DummyPage:
    def __init__(self, element: _DummyElement) -> None:
        self._element: _DummyElement = element

    class _DummyLocator:
        def __init__(self, element: _DummyElement | None) -> None:
            self._element = element

        async def wait_for(self, state: str = "attached", timeout: int | None = None) -> None:
            _ = (state, timeout)
            return None

        async def element_handle(self) -> _DummyElement | None:
            return self._element

        async def all(self) -> list[_DummyElement]:
            return [self._element] if self._element is not None else []

    def locator(self, selector: str) -> _DummyLocator:
        if selector == ".price":
            return _DummyPage._DummyLocator(self._element)
        return _DummyPage._DummyLocator(None)

    async def query_selector(self, selector: str) -> _DummyElement | None:
        if selector == ".price":
            return self._element
        return None


def test_workflow_executor_init_accepts_scraper_config_and_initializes() -> None:
    from scrapers.executor.workflow_executor import WorkflowExecutor

    config = _build_config(
        selectors=[
            SelectorConfig(
                id=None,
                name="price",
                selector=".price",
                attribute="text",
                multiple=False,
                required=True,
            )
        ],
    )

    executor = WorkflowExecutor(config=config, headless=True)

    assert executor.config is config
    assert executor.timeout == 30
    assert executor.max_retries == 2
    assert executor.results == {}
    assert "price" in executor.selectors


@pytest.mark.anyio
async def test_execute_workflow_calls_action_handler_via_action_registry() -> None:
    from scrapers.executor.workflow_executor import WorkflowExecutor

    config = _build_config(workflows=[WorkflowStep(action="extract", name=None, params={"fields": []})])
    fake_browser = _DummyBrowser()
    requested_actions: list[str] = []
    received_params: list[dict[str, object]] = []

    class RecordingAction(BaseAction):
        @override
        def execute(self, params: dict[str, object]):
            received_params.append(params)

    def fake_get_action_class(name: str) -> type[BaseAction]:
        requested_actions.append(name)
        return RecordingAction

    with patch("utils.scraping.playwright_browser.create_playwright_browser", return_value=fake_browser):
        with patch("scrapers.executor.workflow_executor.ActionRegistry.get_action_class", side_effect=fake_get_action_class):
            executor = WorkflowExecutor(config=config)
            await executor.initialize()
            result = await executor.execute_workflow(context={"sku": "ABC123"})

    assert requested_actions == ["extract"]
    assert received_params == [{"fields": []}]
    assert result["success"] is True


@pytest.mark.anyio
async def test_execute_step_dispatches_to_correct_handler_and_substitutes_context() -> None:
    from scrapers.executor.workflow_executor import WorkflowExecutor

    config = _build_config()
    step = WorkflowStep(action="navigate", name=None, params={"url": "{base_url}/item/{sku}"})
    fake_browser = _DummyBrowser()
    requested_actions: list[str] = []
    received_params: list[dict[str, object]] = []

    class RecordingAction(BaseAction):
        @override
        def execute(self, params: dict[str, object]):
            received_params.append(params)

    def fake_get_action_class(name: str) -> type[BaseAction]:
        requested_actions.append(name)
        return RecordingAction

    with patch("utils.scraping.playwright_browser.create_playwright_browser", return_value=fake_browser):
        with patch("scrapers.executor.workflow_executor.ActionRegistry.get_action_class", side_effect=fake_get_action_class):
            executor = WorkflowExecutor(config=config)
            await executor.initialize()
            await executor._execute_step(step, context={"base_url": "https://example.com", "sku": "SKU-1"})

    assert requested_actions == ["navigate"]
    assert received_params == [{"url": "https://example.com/item/SKU-1"}]


@pytest.mark.anyio
async def test_extraction_step_populates_results() -> None:
    from scrapers.executor.workflow_executor import WorkflowExecutor

    config = _build_config(
        selectors=[
            SelectorConfig(
                id=None,
                name="price",
                selector=".price",
                attribute="text",
                multiple=False,
                required=True,
            )
        ],
        workflows=[WorkflowStep(action="extract", name=None, params={"fields": ["price"]})],
    )

    fake_browser = _DummyBrowser(page=_DummyPage(_DummyElement()))

    with patch("utils.scraping.playwright_browser.create_playwright_browser", return_value=fake_browser):
        executor = WorkflowExecutor(config=config)
        await executor.initialize()
        result = await executor.execute_workflow()

    assert result["success"] is True
    assert executor.results["price"] == "$10.99"


@pytest.mark.anyio
async def test_agentic_initialize_creates_browser_use_browser_and_ai_context() -> None:
    from scrapers.executor.workflow_executor import WorkflowExecutor

    class _FakeAIBrowser:
        def __init__(self, *, headless: bool) -> None:
            self.headless = headless

        async def close(self) -> None:
            return None

    class _FakeBrowserUseModule:
        Browser = _FakeAIBrowser

    config = _build_agentic_config(workflows=[WorkflowStep(action="ai_search", name=None, params={"query": "{sku}"})])
    fake_browser = _DummyBrowser()

    with patch("utils.scraping.playwright_browser.create_playwright_browser", return_value=fake_browser):
        with patch("scrapers.executor.workflow_executor.importlib.import_module", return_value=_FakeBrowserUseModule()):
            executor = WorkflowExecutor(config=config, headless=True)
            await executor.initialize()

    assert executor.scraper_type == "agentic"
    assert executor.ai_browser is not None
    assert executor.ai_context["scraper_type"] == "agentic"
    assert executor.ai_context["browser_initialized"] is True
