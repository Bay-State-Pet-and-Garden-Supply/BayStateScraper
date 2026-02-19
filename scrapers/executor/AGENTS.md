# EXECUTOR MODULE

**Scope:** Workflow execution engine - decomposed from god class

## STRUCTURE
```
executor/
├── workflow_executor.py   # Main orchestrator (~589 lines)
├── browser_manager.py     # Browser lifecycle management
├── selector_resolver.py   # Element finding and extraction
├── step_executor.py       # Step execution with retry logic
├── debug_capture.py       # Debug artifact capture
└── normalization.py       # Result normalization
```

## MODULES

### workflow_executor.py
Main orchestrator for workflow execution:
- Loads and validates YAML configs
- Manages browser lifecycle via BrowserManager
- Executes workflow steps sequentially
- Handles errors and retry logic
- Emits events for monitoring

Key class: `WorkflowExecutor`

### browser_manager.py
Browser lifecycle management:
- Initialize/quit Playwright browser
- Navigation with timeout handling
- HTTP status monitoring
- Page state management

Key class: `BrowserManager`

### selector_resolver.py
Element finding and extraction:
- `find_element_safe()` - Safe element lookup with timeout
- `find_elements_safe()` - Multiple element lookup
- `extract_value_from_element()` - Extract text/attributes
- CSS and XPath selector support

Key class: `SelectorResolver`

### step_executor.py
Step execution with retry:
- Execute individual workflow steps
- Retry logic with exponential backoff
- Circuit breaker pattern
- Error classification

Key class: `StepExecutor`

### debug_capture.py
Debug artifact capture:
- Screenshots on failure
- Page source capture
- Console log collection
- Network request logging

Key functions: `capture_screenshot()`, `capture_page_source()`

### normalization.py
Result normalization:
- Price formatting
- Unit standardization
- Text cleanup (strip, lowercase)
- Image URL processing

Key class: `ResultNormalizer`

## ARCHITECTURE

### Before (God Class)
```
WorkflowExecutor (797 lines)
  - Browser management
  - Selector resolution
  - Step execution
  - Debug capture
  - Normalization
```

### After (Decomposed)
```
WorkflowExecutor (589 lines)
  - Orchestration only
  
BrowserManager      - Browser lifecycle
SelectorResolver    - Element finding
StepExecutor        - Step execution
debug_capture       - Debug artifacts
normalization       - Result transformation
```

## USAGE
```python
from scrapers.executor.workflow_executor import WorkflowExecutor
from scrapers.parser.yaml_parser import load_config

config = load_config("scrapers/configs/amazon.yaml")
executor = WorkflowExecutor(config)
results = await executor.run(["sku123"])
```

## CONVENTIONS
- **Async only**: All operations are async
- **Context protocol**: Uses ScraperContext for loose coupling
- **Event emission**: Emits events via EventEmitter
- **Error handling**: Uses WorkflowExecutionError hierarchy

## ANTI-PATTERNS
- **NO** direct browser access (use BrowserManager)
- **NO** sync operations
- **NO** direct DB access
- **NO** bypassing StepExecutor for retry logic
