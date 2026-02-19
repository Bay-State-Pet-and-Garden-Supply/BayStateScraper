# ACTIONS MODULE

**Scope:** Workflow action system - 27 handler implementations

## STRUCTURE
```
actions/
├── handlers/              # 27 action implementations (all async)
│   ├── navigate.py        # Page navigation with HTTP status
│   ├── click.py           # Element clicking
│   ├── extract.py         # Data extraction from selectors
│   ├── extract_and_transform.py  # Extract with transformations
│   ├── transform_value.py # Value transformations
│   ├── input.py           # Form input
│   ├── login.py           # Authentication flows
│   ├── verify.py          # Verification steps
│   ├── wait.py            # Simple wait
│   ├── wait_for.py        # Wait for element
│   ├── wait_for_hidden.py # Wait for element to hide
│   ├── conditional.py     # Conditional execution
│   ├── conditional_skip.py # Conditional skip logic
│   ├── combine.py         # Combine multiple actions
│   ├── script.py          # Custom JavaScript
│   ├── browser.py         # Browser control
│   ├── image.py           # Image extraction
│   ├── table.py           # Table extraction
│   ├── json.py            # JSON extraction
│   ├── sponsored.py       # Sponsored content handling
│   ├── weight.py          # Weight/parsing utilities
│   ├── ai_base.py         # Base for AI actions
│   ├── ai_extract.py      # AI-powered extraction
│   ├── ai_search.py       # AI-powered search
│   ├── ai_validate.py     # AI validation
│   └── anti_detection.py  # Anti-detection measures
├── base.py                # BaseAction abstract class
└── registry.py            # ActionRegistry with auto-discovery
```

## BASE ACTION
```python
from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry

@ActionRegistry.register("my_action")
class MyAction(BaseAction):
    async def execute(self, params: dict[str, Any]) -> Any:
        # Access browser via self.ctx.browser
        # Access results via self.ctx.results
        # Access config via self.ctx.config
        pass
```

## HANDLER CATEGORIES

### Navigation (5)
- `navigate` - Page navigation with HTTP status monitoring
- `click` - Element clicking with retry
- `wait` - Fixed duration wait
- `wait_for` - Wait for element presence
- `wait_for_hidden` - Wait for element to disappear

### Extraction (6)
- `extract` - Extract fields using selectors
- `extract_and_transform` - Extract with inline transformations
- `transform_value` - Transform extracted values
- `table` - Extract table data
- `json` - Extract JSON data
- `image` - Extract image URLs

### AI-Powered (4)
- `ai_base` - Base class for AI actions
- `ai_extract` - AI-powered field extraction
- `ai_search` - AI-powered search/navigation
- `ai_validate` - AI-powered result validation

### Input & Auth (3)
- `input` - Form input filling
- `login` - Authentication flows
- `verify` - Verification steps

### Flow Control (4)
- `conditional` - Conditional action execution
- `conditional_skip` - Skip logic based on conditions
- `combine` - Combine multiple sub-actions
- `script` - Execute custom JavaScript

### Utilities (5)
- `browser` - Browser control operations
- `sponsored` - Handle sponsored/featured content
- `weight` - Weight and unit parsing
- `anti_detection` - Anti-detection measures
- `validation` - Result validation

## CONVENTIONS
- **All async**: Every handler uses `async def execute()`
- **Context access**: Use `self.ctx` for browser, results, config
- **Error handling**: Raise `WorkflowExecutionError` for failures
- **Logging**: Use module logger with context

## ANTI-PATTERNS
- **NO** sync I/O operations
- **NO** direct DB access
- **NO** hardcoded selectors (use YAML params)
- **NO** bypassing ActionRegistry
