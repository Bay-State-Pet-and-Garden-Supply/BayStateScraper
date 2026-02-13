# Event Schema Versioning

## Overview

This document describes the versioning strategy for BayState Scraper events, including backward compatibility guarantees, migration paths, and version negotiation.

**Current Schema Versions:**
- **v1.0** (Legacy): Original event format from `LOG_SCHEMA.md` and `core/events.py`
- **v2.0** (Current): Enhanced schema with structured metadata, timing, and step tracking

---

## Version Negotiation Strategy

### Producer-Side Versioning

Events are versioned at the producer level through an explicit `version` field:

```json
{
  "version": "2.0",
  "event_type": "job.started",
  "timestamp": "2025-02-12T10:30:00.000Z",
  "run_id": "run_20250212_103000"
}
```

**Rules:**
1. **v1 producers** emit events WITHOUT the `version` field
2. **v2 producers** MUST include `"version": "2.0"`
3. **Default interpretation**: Events without a version field are treated as v1

### Consumer Detection

Consumers should detect versions using this priority:

```python
def detect_event_version(event: dict) -> str:
    """Detect schema version from event data."""
    # Explicit version field (v2+)
    if "version" in event:
        return event["version"]
    
    # v1 events have 'job_id' but not 'run_id' or 'version'
    if "job_id" in event and "run_id" not in event:
        return "1.0"
    
    # Default fallback
    return "1.0"
```

---

## Backward Compatibility Approach

### Guiding Principles

1. **Additive Only**: New fields are added, existing fields are never removed
2. **Optional New Fields**: All v2-specific fields are optional from v1 perspective
3. **Dual Field Support**: Critical fields have v1/v2 aliases (e.g., `job_id` → `run_id`)
4. **Graceful Degradation**: v1 consumers ignore unknown fields
5. **Schema Validation**: Strict validation only on version-specific required fields

### Field Compatibility Matrix

| v1 Field | v2 Field | Compatibility | Notes |
|----------|----------|---------------|-------|
| `event_type` | `event_type` | ✅ Identical | Same enum values |
| `timestamp` | `timestamp` | ✅ Identical | ISO 8601 format |
| `job_id` | `run_id` | ✅ Dual support | `job_id` kept for backward compatibility |
| `severity` | `severity` | ✅ Identical | Same enum values |
| `scraper_name` | `scraper` | ✅ Dual support | Both fields accepted |
| `payload` | `data` | ✅ Merged | v1 `payload` maps to v2 `data` |
| — | `timing` | ➕ New | Structured timing metadata |
| — | `step` | ➕ New | Step execution details |
| — | `selector` | ➕ New | Selector resolution results |
| — | `extraction` | ➕ New | Extraction results with confidence |
| — | `version` | ➕ New | Schema version identifier |

### Required vs Optional Fields

**v1 Required Fields:**
- `event_type`
- `timestamp`
- `level` (mapped to `severity` in v2)
- `logger`
- `message`
- `job_id`
- `runner_name`

**v2 Required Fields:**
- `event_type`
- `timestamp`
- `version` (optional for backward compatibility, defaults to "1.0")

**v2 Recommended Fields:**
- `run_id` (preferred over `job_id`)
- `event_id`
- `severity`

---

## Migration Path from v1 to v2

### Phase 1: Dual-Mode Emitters (Current)

Emitters support both v1 and v2 formats:

```python
class EventEmitter:
    def __init__(self, version: str = "2.0"):
        self.version = version
    
    def emit(self, event_type: str, **kwargs):
        event = {
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        
        if self.version == "2.0":
            event["version"] = "2.0"
            event["run_id"] = kwargs.get("run_id")
            # v2-specific fields...
        else:
            event["job_id"] = kwargs.get("job_id")
            # v1-compatible fields...
        
        return event
```

### Phase 2: Consumer Updates

Update consumers to handle both formats:

```python
class EventConsumer:
    def process_event(self, event: dict):
        version = detect_event_version(event)
        
        # Normalize to internal model
        run_id = event.get("run_id") or event.get("job_id")
        scraper = event.get("scraper") or event.get("scraper_name")
        
        if version == "2.0":
            self._process_v2(event)
        else:
            self._process_v1(event)
```

### Phase 3: v1 Deprecation (Future)

Once all consumers are v2-compatible:

1. Mark `job_id` as deprecated in documentation
2. Add deprecation warnings in emitters
3. Eventually remove v1 support in major version bump

---

## Event Type Mappings

### v1 → v2 Event Type Evolution

| v1 Type (core/events.py) | v2 Type | Status | Notes |
|--------------------------|---------|--------|-------|
| `JOB_STARTED` | `job.started` | ✅ Renamed | Dot notation standard |
| `JOB_COMPLETED` | `job.completed` | ✅ Renamed | Dot notation standard |
| `JOB_FAILED` | `job.failed` | ✅ Renamed | Dot notation standard |
| `SCRAPER_STARTED` | `scraper.started` | ✅ Renamed | Dot notation standard |
| `SKU_SUCCESS` | `sku.success` | ✅ Renamed | Dot notation standard |
| `SKU_FAILED` | `sku.failed` | ✅ Renamed | Dot notation standard |
| `SELECTOR_FOUND` | `selector.resolved` | ✅ Enhanced | Now includes count, value |
| — | `step.started` | ➕ New | Step lifecycle tracking |
| — | `step.completed` | ➕ New | Step lifecycle tracking |
| — | `extraction.completed` | ➕ New | Detailed extraction results |

### Legacy Type Support

v2 consumers SHOULD accept both formats:

```python
EVENT_TYPE_ALIASES = {
    # v1 → v2 mappings
    "JOB_STARTED": "job.started",
    "JOB_COMPLETED": "job.completed",
    "SELECTOR_FOUND": "selector.resolved",
    # ... etc
}

def normalize_event_type(event_type: str) -> str:
    return EVENT_TYPE_ALIASES.get(event_type, event_type)
```

---

## Example Events

### v1 Legacy Event

```json
{
  "timestamp": "2025-01-21T10:30:05.123Z",
  "level": "INFO",
  "logger": "scraper_backend.scrapers.executor",
  "message": "Successfully navigated to product page",
  "job_id": "job_123",
  "runner_name": "worker-01",
  "scraper_name": "amazon_products",
  "sku": "B08X5H",
  "action": "navigate",
  "duration_ms": 1250
}
```

### v2 Equivalent Event

```json
{
  "version": "2.0",
  "event_type": "step.completed",
  "timestamp": "2025-01-21T10:30:05.123Z",
  "run_id": "job_123",
  "event_id": "evt_xyz789",
  "severity": "info",
  "runner_name": "worker-01",
  "scraper": "amazon_products",
  "sku": "B08X5H",
  "step": {
    "index": 1,
    "action": "navigate",
    "name": "Navigate to product page",
    "status": "completed"
  },
  "timing": {
    "started_at": "2025-01-21T10:30:03.873Z",
    "completed_at": "2025-01-21T10:30:05.123Z",
    "duration_ms": 1250
  }
}
```

### v2 Job Lifecycle Events

#### Job Started

```json
{
  "version": "2.0",
  "event_type": "job.started",
  "timestamp": "2025-02-12T10:30:00.000Z",
  "run_id": "run_20250212_103000",
  "event_id": "evt_start_001",
  "severity": "info",
  "runner_name": "worker-01",
  "data": {
    "total_skus": 100,
    "scrapers": ["bradley", "amazon"],
    "max_workers": 4,
    "test_mode": false
  }
}
```

#### Scraper Started

```json
{
  "version": "2.0",
  "event_type": "scraper.started",
  "timestamp": "2025-02-12T10:30:00.500Z",
  "run_id": "run_20250212_103000",
  "scraper": "bradley",
  "worker_id": "worker-01",
  "data": {
    "total_skus": 50
  }
}
```

#### Step Started

```json
{
  "version": "2.0",
  "event_type": "step.started",
  "timestamp": "2025-02-12T10:30:01.000Z",
  "run_id": "run_20250212_103000",
  "scraper": "bradley",
  "sku": "SKU12345",
  "step": {
    "index": 0,
    "action": "navigate",
    "name": "Navigate to product page"
  }
}
```

#### Step Completed

```json
{
  "version": "2.0",
  "event_type": "step.completed",
  "timestamp": "2025-02-12T10:30:02.250Z",
  "run_id": "run_20250212_103000",
  "scraper": "bradley",
  "sku": "SKU12345",
  "step": {
    "index": 0,
    "action": "navigate",
    "name": "Navigate to product page",
    "status": "completed"
  },
  "timing": {
    "started_at": "2025-02-12T10:30:01.000Z",
    "completed_at": "2025-02-12T10:30:02.250Z",
    "duration_ms": 1250
  }
}
```

#### Selector Resolved

```json
{
  "version": "2.0",
  "event_type": "selector.resolved",
  "timestamp": "2025-02-12T10:30:02.500Z",
  "run_id": "run_20250212_103000",
  "scraper": "bradley",
  "sku": "SKU12345",
  "selector": {
    "name": "product_price",
    "value": "span.price",
    "found": true,
    "count": 1,
    "attribute": "text"
  }
}
```

#### Selector Missing

```json
{
  "version": "2.0",
  "event_type": "selector.resolved",
  "timestamp": "2025-02-12T10:30:02.600Z",
  "run_id": "run_20250212_103000",
  "scraper": "bradley",
  "sku": "SKU12345",
  "selector": {
    "name": "rating",
    "value": "span.rating",
    "found": false,
    "count": 0,
    "error": "Timeout 30000ms exceeded"
  }
}
```

#### Extraction Completed

```json
{
  "version": "2.0",
  "event_type": "extraction.completed",
  "timestamp": "2025-02-12T10:30:02.750Z",
  "run_id": "run_20250212_103000",
  "scraper": "bradley",
  "sku": "SKU12345",
  "extraction": {
    "field_name": "price",
    "value": "$19.99",
    "confidence": 0.95,
    "status": "SUCCESS"
  }
}
```

#### SKU Success

```json
{
  "version": "2.0",
  "event_type": "sku.success",
  "timestamp": "2025-02-12T10:30:03.000Z",
  "run_id": "run_20250212_103000",
  "scraper": "bradley",
  "sku": "SKU12345",
  "timing": {
    "duration_ms": 2000
  },
  "data": {
    "extracted_data": {
      "name": "Product Name",
      "price": "$19.99",
      "availability": "In Stock"
    }
  }
}
```

#### Scraper Completed

```json
{
  "version": "2.0",
  "event_type": "scraper.completed",
  "timestamp": "2025-02-12T10:45:00.000Z",
  "run_id": "run_20250212_103000",
  "scraper": "bradley",
  "worker_id": "worker-01",
  "timing": {
    "duration_ms": 900000
  },
  "progress": {
    "current": 50,
    "total": 50,
    "successful": 48,
    "failed": 2
  },
  "data": {
    "processed": 50,
    "successful": 48,
    "failed": 2,
    "duration_seconds": 900
  }
}
```

#### Scraper Failed

```json
{
  "version": "2.0",
  "event_type": "scraper.failed",
  "timestamp": "2025-02-12T10:20:00.000Z",
  "run_id": "run_20250212_103000",
  "scraper": "amazon",
  "worker_id": "worker-02",
  "severity": "error",
  "error": {
    "type": "BrowserCrashedError",
    "message": "Browser process terminated unexpectedly",
    "retryable": true
  }
}
```

#### SKU Processing

```json
{
  "version": "2.0",
  "event_type": "sku.processing",
  "timestamp": "2025-02-12T10:30:04.000Z",
  "run_id": "run_20250212_103000",
  "scraper": "bradley",
  "worker_id": "worker-01",
  "sku": "SKU12346"
}
```

#### SKU No Results

```json
{
  "version": "2.0",
  "event_type": "sku.no_results",
  "timestamp": "2025-02-12T10:30:08.000Z",
  "run_id": "run_20250212_103000",
  "scraper": "bradley",
  "worker_id": "worker-01",
  "sku": "SKU99999",
  "severity": "warning",
  "data": {
    "reason": "Product not found on page",
    "sku_type": "test",
    "is_passing": false
  }
}
```

#### Step Failed

```json
{
  "version": "2.0",
  "event_type": "step.failed",
  "timestamp": "2025-02-12T10:30:05.500Z",
  "run_id": "run_20250212_103000",
  "scraper": "bradley",
  "sku": "SKU12345",
  "severity": "error",
  "step": {
    "index": 3,
    "action": "click",
    "name": "Click add to cart button",
    "status": "failed",
    "retry_count": 3,
    "max_retries": 3
  },
  "timing": {
    "started_at": "2025-02-12T10:30:05.000Z",
    "completed_at": "2025-02-12T10:30:05.500Z",
    "duration_ms": 500
  },
  "error": {
    "type": "ElementNotFoundError",
    "message": "Selector '.add-to-cart' not found after 30s",
    "retryable": false
  }
}
```

#### Job Completed

```json
{
  "version": "2.0",
  "event_type": "job.completed",
  "timestamp": "2025-02-12T11:15:00.000Z",
  "run_id": "run_20250212_103000",
  "event_id": "evt_complete_001",
  "severity": "info",
  "runner_name": "worker-01",
  "timing": {
    "started_at": "2025-02-12T10:30:00.000Z",
    "completed_at": "2025-02-12T11:15:00.000Z",
    "duration_ms": 2700000
  },
  "progress": {
    "current": 100,
    "total": 100,
    "percentage": 100,
    "successful": 95,
    "failed": 5
  },
  "data": {
    "successful": 95,
    "failed": 5,
    "duration_seconds": 2700,
    "success_rate": 95.0
  }
}
```

---

## Validation Strategy

### Schema Validation Levels

1. **Strict v2**: All v2 required fields present, no unknown fields
2. **Lenient v2**: Required fields present, unknown fields allowed
3. **Backward Compatible**: Accepts v1 and v2, validates based on detected version

### Python Validation Example

```python
import json
from jsonschema import validate, ValidationError

def validate_event(event: dict) -> tuple[bool, str]:
    """Validate event against appropriate schema version."""
    version = detect_event_version(event)
    
    try:
        if version == "2.0":
            validate(instance=event, schema=SCHEMA_V2)
        else:
            validate(instance=event, schema=SCHEMA_V1)
        return True, f"Valid {version} event"
    except ValidationError as e:
        return False, str(e)
```

---

## Future Versions

### Version 2.1 (Planned)

- Add `correlation_id` for distributed tracing
- Add `parent_event_id` for event hierarchies
- Extend `context` with standardized fields

### Version 3.0 (Future)

- Remove deprecated `job_id` field (use `run_id`)
- Remove legacy event type aliases
- Make `version` field required

---

## References

- [event-schema-v2.json](./event-schema-v2.json) - JSON Schema definition
- [LOG_SCHEMA.md](./LOG_SCHEMA.md) - v1 schema documentation
- `core/events.py` - Event emitter implementation
- `scrapers/events/` - Test Lab event handlers
