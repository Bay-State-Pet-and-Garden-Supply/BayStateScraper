# EVENTS MODULE

**Scope:** Event-driven architecture for real-time monitoring and communication

## STRUCTURE
```
events/
├── emitter.py             # EventEmitter - central event bus
├── websocket_server.py    # WebSocket server for real-time streaming
├── handlers/              # Event handlers
│   ├── console.py         # Console logging handler
│   ├── extraction.py      # Extraction event handler
│   ├── login.py           # Login event handler
│   └── selector.py        # Selector event handler
├── base.py                # Base event classes
├── extraction.py          # Extraction event definitions
├── login.py               # Login event definitions
└── selector.py            # Selector event definitions
```

## EVENT EMITTER

### EventEmitter
Central event bus with WebSocket support:
```python
from scrapers.events.emitter import EventEmitter

emitter = EventEmitter()
emitter.on("extraction.complete", handler)
emitter.emit("extraction.complete", data)
```

Features:
- Event subscription with `on(event, handler)`
- Event emission with `emit(event, data)`
- Async handler support
- WebSocket broadcasting
- Event persistence

## EVENT TYPES

### Extraction Events
- `extraction.start` - Extraction started
- `extraction.complete` - Extraction finished
- `extraction.error` - Extraction failed
- `extraction.field_found` - Field extracted

### Login Events
- `login.start` - Login process started
- `login.success` - Login successful
- `login.failed` - Login failed
- `login.captcha_detected` - CAPTCHA encountered

### Selector Events
- `selector.attempt` - Selector lookup attempted
- `selector.found` - Selector found element
- `selector.not_found` - Selector missed element
- `selector.timeout` - Selector timed out

### Workflow Events
- `workflow.start` - Workflow started
- `workflow.step` - Step executed
- `workflow.complete` - Workflow finished
- `workflow.error` - Workflow error

## WEBSOCKET SERVER

Real-time event streaming via WebSocket:
```python
from scrapers.events.websocket_server import WebSocketServer

server = WebSocketServer(port=8765)
await server.start()
```

Use cases:
- Live scraping monitoring
- Real-time debugging
- External tool integration
- Dashboard updates

## HANDLERS

### Console Handler
Logs events to console with structured formatting

### Extraction Handler
Tracks extraction progress and results

### Login Handler
Monitors authentication flow

### Selector Handler
Logs selector performance and issues

## USAGE IN ACTIONS

```python
from scrapers.actions.base import BaseAction

class MyAction(BaseAction):
    async def execute(self, params):
        # Emit custom event
        if self.ctx.event_emitter:
            self.ctx.event_emitter.emit("my_action.start", {
                "action": "my_action",
                "params": params
            })
        
        # Do work...
        
        # Emit completion
        if self.ctx.event_emitter:
            self.ctx.event_emitter.emit("my_action.complete", {
                "result": result
            })
```

## CONVENTIONS
- **Always check**: Verify `event_emitter` exists before emitting
- **Structured data**: Emit dictionaries with consistent keys
- **Event names**: Use dot notation (e.g., `category.action`)
- **Async handlers**: Handlers can be async

## ANTI-PATTERNS
- **NO** emitting without checking emitter exists
- **NO** blocking operations in event handlers
- **NO** circular event chains
- **NO** sensitive data in events (passwords, keys)
