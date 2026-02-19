# SCRAPERS MODULE

**Scope:** Scraping domain - actions, workflows, execution engine, events

## STRUCTURE
```
scrapers/
├── actions/               # Action system
│   ├── handlers/          # 27 action implementations (all async)
│   │   ├── navigate.py    # Page navigation
│   │   ├── click.py       # Element clicking
│   │   ├── extract.py     # Data extraction
│   │   ├── ai_extract.py  # AI-powered extraction
│   │   └── ... (23 more)
│   ├── base.py            # BaseAction abstract class
│   └── registry.py        # ActionRegistry with auto-discovery
├── executor/              # Workflow execution engine (decomposed)
│   ├── workflow_executor.py      # Main orchestrator
│   ├── browser_manager.py        # Browser lifecycle
│   ├── selector_resolver.py      # Element finding/extraction
│   ├── step_executor.py          # Step execution with retry
│   ├── debug_capture.py          # Debug artifact capture
│   └── normalization.py          # Result normalization
├── events/                # Event system
│   ├── emitter.py         # EventEmitter with WebSocket
│   ├── handlers/          # Event handlers
│   └── websocket_server.py # WebSocket integration
├── configs/               # YAML scraper definitions (12 files)
│   ├── amazon.yaml
│   ├── walmart.yaml
│   ├── ai-template.yaml
│   └── ...
├── context.py             # ScraperContext Protocol
├── models/                # Pydantic models
│   ├── config.py          # ScraperConfig
│   └── result.py          # ScrapeResult
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

### Event System
Event-driven architecture for real-time monitoring:
- **EventEmitter**: Central event bus with WebSocket support
- **Handlers**: console, extraction, login, selector events
- **WebSocket Server**: Real-time event streaming

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
- **NO** bypassing EventEmitter for status updates

## RELATED
- Parent: `../AGENTS.md` (root scraper overview)
- Actions: `./actions/AGENTS.md` (action system details)
- Executor: `./executor/AGENTS.md` (workflow engine)
- Events: `./events/AGENTS.md` (event system)

## TESTING
Action tests: `tests/test_action_registry.py`
Executor tests: `tests/test_workflow_executor.py`
