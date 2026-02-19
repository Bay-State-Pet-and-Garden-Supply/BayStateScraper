# RUNNER MODULE

**Scope:** Execution modes - full scrape, chunk worker, realtime listener

## STRUCTURE
```
runner/
├── __init__.py          # Package exports run_job
├── __main__.py          # CLI entry point
├── cli.py               # Argument parsing (--mode)
├── full_mode.py         # Full scraper execution
├── chunk_mode.py        # Chunk worker (distributed)
└── realtime_mode.py     # Supabase Realtime listener
```

## EXECUTION MODES

### Full Mode
`full_mode.py` - Complete scraper execution:
- Run all scrapers for given SKUs
- Sequential or parallel execution
- Full result collection

### Chunk Mode
`chunk_mode.py` - Distributed chunk worker:
- Claim chunks from API
- Process assigned work
- Report results
- Autonomous claiming (no coordinator needed after start)

### Realtime Mode
`realtime_mode.py` - Event-driven execution:
- Listen to Supabase Realtime
- React to job creation events
- Immediate execution

## USAGE

```python
# Import and run
from runner import run_job
from runner.full_mode import run_full_mode
from runner.chunk_mode import run_chunk_worker_mode
from runner.realtime_mode import run_realtime_mode

# CLI usage
python runner.py --mode full --job-id <uuid>
python runner.py --mode chunk_worker --runner-name worker-1
python runner.py --mode realtime
```

## ENTRY POINTS
- `daemon.py` uses `run_job()` with mode dispatch
- `runner.py` is thin wrapper (5 lines)
- Docker ENTRYPOINT: `python daemon.py`

## RELATED
- Parent: `../AGENTS.md` (root scraper overview)
- Core: `../core/AGENTS.md` (infrastructure services)
- Scrapers: `../scrapers/AGENTS.md` (scraping domain)

## ANTI-PATTERNS
- **NO** mode-specific logic outside this package
- **NO** direct scraper instantiation (use WorkflowExecutor)
