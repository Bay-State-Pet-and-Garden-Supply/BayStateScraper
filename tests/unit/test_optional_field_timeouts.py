from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from scrapers.actions.handlers.extract import (
    DEFAULT_OPTIONAL_FIELD_TIMEOUT_MS,
    ExtractAction,
    ExtractMultipleAction,
)
from scrapers.actions.handlers.extract_transform import ExtractAndTransformAction
from scrapers.models.config import SelectorConfig


@dataclass
class _Call:
    selector: str
    required: bool | None
    timeout: int | None


class _DummyContext:
    def __init__(self, selectors: dict[str, SelectorConfig]) -> None:
        self.selectors = selectors
        self.results: dict[str, Any] = {}
        self.single_calls: list[_Call] = []
        self.multiple_calls: list[_Call] = []

    def resolve_selector(self, identifier: str) -> SelectorConfig | None:
        return self.selectors.get(identifier)

    async def find_element_safe(
        self,
        selector: str,
        required: bool = True,
        timeout: int | None = None,
    ) -> Any:
        self.single_calls.append(_Call(selector=selector, required=required, timeout=timeout))
        return None

    async def find_elements_safe(self, selector: str, timeout: int | None = None) -> list[Any]:
        self.multiple_calls.append(_Call(selector=selector, required=None, timeout=timeout))
        return []

    async def _extract_value_from_element(self, _element: Any, _attribute: str | None = None) -> Any:
        return None

    async def extract_value_from_element(self, _element: Any, _attribute: str | None = None) -> Any:
        return None


def _selector(name: str, selector: str, *, multiple: bool = False, required: bool = True) -> SelectorConfig:
    return SelectorConfig(name=name, selector=selector, attribute="text", multiple=multiple, required=required)


def test_extract_action_uses_fast_timeout_and_non_required_lookup() -> None:
    ctx = _DummyContext({"Weight": _selector("Weight", ".weight", required=True)})
    action = ExtractAction(ctx)

    asyncio.run(action.execute({"fields": ["Weight"]}))

    assert len(ctx.single_calls) == 1
    call = ctx.single_calls[0]
    assert call.required is True
    assert call.timeout is None


def test_extract_action_respects_field_timeout_override() -> None:
    ctx = _DummyContext({"UPC": _selector("UPC", ".upc", required=False)})
    action = ExtractAction(ctx)

    asyncio.run(action.execute({"fields": ["UPC"], "field_timeout_ms": 700}))

    assert len(ctx.single_calls) == 1
    assert ctx.single_calls[0].timeout == 700


def test_extract_action_uses_default_optional_timeout_for_non_required_fields() -> None:
    ctx = _DummyContext({"UPC": _selector("UPC", ".upc", required=False)})
    action = ExtractAction(ctx)

    asyncio.run(action.execute({"fields": ["UPC"]}))

    assert len(ctx.single_calls) == 1
    assert ctx.single_calls[0].required is False
    assert ctx.single_calls[0].timeout == DEFAULT_OPTIONAL_FIELD_TIMEOUT_MS


def test_extract_multiple_uses_default_optional_timeout_when_not_required() -> None:
    ctx = _DummyContext({"Images": _selector("Images", "img", multiple=True, required=False)})
    action = ExtractMultipleAction(ctx)

    asyncio.run(action.execute({"field": "Images", "selector": "Images"}))

    assert len(ctx.multiple_calls) == 1
    assert ctx.multiple_calls[0].timeout == DEFAULT_OPTIONAL_FIELD_TIMEOUT_MS


def test_extract_and_transform_uses_short_timeout_only_for_optional_fields() -> None:
    ctx = _DummyContext({})
    action = ExtractAndTransformAction(ctx)

    asyncio.run(
        action.execute(
            {
                "fields": [
                    {"name": "required_field", "selector": "#required", "required": True},
                    {"name": "optional_field", "selector": "#optional", "required": False},
                ]
            }
        )
    )

    assert [call.timeout for call in ctx.single_calls] == [None, 1500]
