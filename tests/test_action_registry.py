from __future__ import annotations

import pkgutil
import uuid
from pathlib import Path
from typing_extensions import override

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry


def test_auto_discover_actions_finds_all_22_handler_modules() -> None:
    handlers_path = Path(__file__).resolve().parent.parent / "scrapers" / "actions" / "handlers"
    discovered_modules = [name for _, name, _ in pkgutil.iter_modules([str(handlers_path)]) if name != "__init__"]

    ActionRegistry.auto_discover_actions()

    assert len(discovered_modules) == 22
    assert len(ActionRegistry.get_registered_actions()) >= 22


def test_get_action_returns_correct_handler_class() -> None:
    from scrapers.actions.handlers.navigate import NavigateAction

    ActionRegistry.auto_discover_actions()

    action_class = ActionRegistry.get_action_class("navigate")
    assert action_class is NavigateAction


def test_register_decorator_registers_handler_class() -> None:
    action_name = f"custom_action_{uuid.uuid4().hex}"
    action_name_obj: object = action_name

    @ActionRegistry.register(str(action_name_obj))
    class CustomAction(BaseAction):
        @override
        async def execute(self, params: dict[str, object]) -> None:
            return None

    assert ActionRegistry.get_action_class(action_name) is CustomAction
