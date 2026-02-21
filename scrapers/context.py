"""ScraperContext Protocol for decoupling actions from executor."""

from __future__ import annotations

from typing import Protocol, Any
from scrapers.models.config import ScraperConfig, SelectorConfig, WorkflowStep


class ScraperContext(Protocol):
    """Protocol defining the interface between actions and executor."""

    # Data attributes
    results: dict[str, Any]
    config: ScraperConfig
    context: dict[str, Any]
    ai_context: dict[str, Any]
    scraper_type: str

    # Browser interface
    browser: Any  # Has .page attribute
    ai_browser: Any

    async def find_element_safe(self, selector: str, required: bool = True, timeout: int | None = None) -> Any: ...

    async def find_elements_safe(self, selector: str, timeout: int | None = None) -> list[Any]: ...

    async def extract_value_from_element(self, element: Any, attribute: str | None = None) -> Any: ...

    async def _extract_value_from_element(self, element: Any, attribute: str | None = None) -> Any: ...

    def resolve_selector(self, identifier: str) -> SelectorConfig | None: ...

    # Workflow control

    workflow_stopped: bool
    first_navigation_done: bool

    async def dispatch_step(self, step: WorkflowStep) -> Any: ...

    # Session management
    def is_session_authenticated(self) -> bool: ...

    def mark_session_authenticated(self) -> None: ...

    # Metadata
    event_emitter: Any | None
    worker_id: str | None
    timeout: int
    is_ci: bool
    anti_detection_manager: Any | None
