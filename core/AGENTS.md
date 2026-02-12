# CORE MODULE

**Scope:** Infrastructure services - API client, events, retry, health monitoring

## STRUCTURE
```
core/
├── api_client.py              # API communication with coordinator
├── events.py                  # Event bus system
├── retry_executor.py          # Retry logic with circuit breaker
├── realtime_manager.py        # Supabase Realtime integration
├── scheduler.py               # Job scheduling
├── memory_manager.py          # Memory monitoring
├── scraper_health_monitor.py  # Health checks
├── failure_analytics.py       # Failure tracking
├── failure_classifier.py      # Failure categorization
├── adaptive_retry_strategy.py # Intelligent retry
├── settings_manager.py        # Configuration management
├── scraper_cache.py           # Caching layer
├── field_mapping.py           # Data field mapping
├── models.py                  # Shared Pydantic models
├── local_storage/             # Local dataset/queue storage
│   ├── dataset.py
│   ├── key_value_store.py
│   └── request_queue.py
└── database/                  # DB interfaces (deprecated stubs)
    └── supabase_sync.py       # Legacy compat stub
```

## KEY SERVICES

### API Client
`api_client.py` - Central communication with BayStateApp coordinator:
- Auth via `X-API-Key` header
- Job fetching and result callbacks
- NO direct database access

### Event Bus
`events.py` - Structured event system:
- Event emission/handling
- WebSocket support for realtime
- Event persistence

### Retry Infrastructure
- `retry_executor.py` - Core retry with circuit breaker
- `adaptive_retry_strategy.py` - ML-based retry timing
- `failure_classifier.py` - Categorize failures
- `failure_analytics.py` - Track patterns

### Realtime
`realtime_manager.py` - Supabase Realtime WebSocket:
- Listen for job assignments
- Real-time status updates
- V2 protocol support

## ANTI-PATTERNS
- **NO** database credentials in runners
- **NO** direct Supabase/PostgreSQL connections
- **NO** bypassing APIClient for data

## DEPRECATED
`core/database/supabase_sync.py` - Legacy stub, kept for compat. Use APIClient instead.
