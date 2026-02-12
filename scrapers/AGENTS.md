# SCRAPERS MODULE

**Scope:** Scraping domain - actions, workflows, execution engine

## STRUCTURE
```
scrapers/
├── actions/
│   ├── handlers/          # 21 action implementations (all async)
│   │   ├── navigate.py    # Page navigation
│   │   ├── click.py       # Element clicking
│   │   ├── extract.py     # Data extraction
│   │   ├── input.py       # Form input
│   │   ├── login.py       # Authentication flows
│   │   └── ... (16 more)
│   ├── base.py            # BaseAction abstract class
│   ├── registry.py        # ActionRegistry with auto-discovery
│   └── __init__.py
├── executor/              # Workflow execution engine (decomposed)
│   ├── workflow_executor.py      # Main orchestrator (581 lines)
│   ├── browser_manager.py        # Browser lifecycle
│   ├── selector_resolver.py      # Element finding/extraction
│   ├── step_executor.py          # Step execution with retry
│   ├── debug_capture.py          # Debug artifact capture
│   └── normalization.py          # Result normalization
├── configs/               # YAML scraper definitions
│   ├── amazon.yaml
│   ├── walmart.yaml
│   └── ...
├── context.py             # ScraperContext Protocol
├── models/
│   ├── config.py          # ScraperConfig Pydantic models
│   └── result.py          # ScrapeResult Pydantic model
└── parser/
    └── yaml_parser.py     # YAML config parsing
```

## KEY CONCEPTS

### ScraperContext Protocol
`context.py` defines the interface between actions and executor:
```python
class ScraperContext(Protocol):
    results: dict[str, Any]
    config: ScraperConfig
    browser: Any  # Has .page attribute
    
    async def find_element_safe(self, selector: str) -> Any: ...
    async def dispatch_step(self, step: WorkflowStep) -> Any: ...
```

Actions receive `self.ctx` (ScraperContext) instead of full WorkflowExecutor.

### Action Registration
All actions auto-register via decorator:
```python
@ActionRegistry.register("navigate")
class NavigateAction(BaseAction):
    async def execute(self, params: dict[str, Any]) -> None:
        url = params["url"]
        await self.ctx.browser.page.goto(url)
```

### Executor Modules (Decomposed)
WorkflowExecutor delegates to focused modules:
- **browser_manager**: init, quit, navigate, HTTP status
- **selector_resolver**: find_element_safe, find_elements_safe, extract_value
- **step_executor**: execute_step with retry logic
- **debug_capture**: screenshots, page source on failure
- **normalization**: result transformations

## ADDING ACTIONS
1. Create `{name}.py` in `actions/handlers/`
2. Inherit `BaseAction`
3. Use `@ActionRegistry.register("{name}")`
4. Implement `async def execute(self, params)`
5. Access via `self.ctx` (browser, results, config)

## ANTI-PATTERNS
- **NO** selenium references
- **NO** sync browser operations (use async)
- **NO** direct DB access (use API callbacks)
- **NO** hardcoded site logic (use YAML params)

## TESTING
Action tests: `tests/test_action_registry.py`
Executor tests: `tests/test_workflow_executor.py`
