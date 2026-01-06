from __future__ import annotations

# Lazy imports to avoid circular import issues
# (retry_executor imports exceptions, which would trigger this __init__)


def __getattr__(name: str):
    """Lazy import to avoid circular imports."""
    if name == "WorkflowExecutor":
        from .executor import WorkflowExecutor

        return WorkflowExecutor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["WorkflowExecutor"]
