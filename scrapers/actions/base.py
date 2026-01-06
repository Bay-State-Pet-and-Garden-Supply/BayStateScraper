from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scrapers.executor.workflow_executor import WorkflowExecutor


class BaseAction(ABC):
    """Abstract base class for all workflow actions."""

    def __init__(self, executor: "WorkflowExecutor") -> None:
        self.executor = executor

    @abstractmethod
    def execute(self, params: dict[str, Any]) -> Any:
        """
        Execute the action with the given parameters.

        Args:
            params: Dictionary of parameters for the action

        Returns:
            Result of the action execution
        """
        pass

    @property
    def name(self) -> str:
        """Return the name of the action."""
        return self.__class__.__name__
