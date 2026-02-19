# AI Scraper Documentation

The BayStateScraper v0.2.0 introduces AI-powered scraping capabilities through agentic browser control. This document covers setup, configuration, and best practices for using AI scrapers.

## Overview

The AI scraper system uses browser-use to provide universal product discovery without requiring pre-configured CSS selectors. The system includes:

- **Universal Extraction**: AI identifies and extracts product data automatically
- **Official Source Identification**: Uses Brave Search + LLM to find manufacturer pages
- **Cost Tracking**: Built-in budget enforcement to prevent runaway API spending
- **Smart Fallback**: Automatically falls back to static scraping if needed
- **Metrics Collection**: Prometheus-compatible metrics for monitoring

## Architecture

The AI scraper system consists of several interconnected components:

```
┌─────────────────────────────────────────────────────────────────┐
│                    AI Scraper Components                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐    ┌──────────────────┐                 │
│  │  ai_cost_tracker │    │   ai_metrics     │                 │
│  │  - Cost limits   │    │  - Extraction    │                 │
│  │  - Circuit break │    │    counts        │                 │
│  │  - Budget check  │    │  - Success rates │                 │
│  └────────┬────────┘    └────────┬─────────┘                 │
│           │                       │                             │
│           └───────────┬───────────┘                             │
│                       ▼                                         │
│           ┌────────────────────────┐                           │
│           │    AIFallbackManager    │                           │
│           │   AI → Traditional      │                           │
│           └────────────┬───────────┘                           │
│                        │                                        │
│    ┌───────────────────┼───────────────────┐                  │
│    ▼                   ▼                   ▼                  │
│ ┌──────────┐   ┌──────────────┐   ┌─────────────┐            │
│ │ ai_search │   │  ai_extract  │   │ai_validate │            │
│ │           │   │              │   │             │            │
│ │ Brave     │   │  browser-use │   │ Confidence  │            │
│ │ Search    │   │  Agent       │   │ threshold   │            │
│ └───────────┘   └──────────────┘   └─────────────┘            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Installation

### Prerequisites

AI scrapers require the following dependencies:

```bash
# Core dependencies (already in requirements.txt)
pip install browser-use openai httpx

# Ensure Playwright is installed
python -m playwright install chromium
```

### API Keys

AI scrapers require two API keys in your `.env` file:

```bash
# OpenAI API key (required for AI extraction)
OPENAI_API_KEY=sk-...

# Brave Search API key (required for ai_search action)
BRAVE_API_KEY=bs-...
```

Get your keys from:
- OpenAI: https://platform.openai.com/api-keys
- Brave: https://brave.com/search/api/

## Configuration

### Scraper Type

To enable AI features, set `scraper_type` to `"agentic"` in your YAML config:

```yaml
name: "my-ai-scraper"
base_url: "https://example.com"
scraper_type: "agentic"  # Required for AI features
```

### AI Configuration Section

The `ai_config` section provides fine-grained control:

```yaml
ai_config:
  # AI tool to use (currently only browser-use is supported)
  tool: "browser-use"
  
  # Natural language task describing what the AI should do
  task: "Extract product information including name, brand, price"
  
  # Maximum steps the AI agent can take (1-50)
  max_steps: 10
  
  # Minimum confidence score for accepting results (0.0-1.0)
  confidence_threshold: 0.7
  
  # OpenAI model to use
  llm_model: "gpt-4o-mini"
  
  # Enable GPT-4 Vision for complex pages
  use_vision: true
  
  # Run browser in headless mode
  headless: true
```

### Model Options

| Model | Cost | Best For |
|-------|------|----------|
| `gpt-4o-mini` | $0.001/1K tokens | Simple extractions, high volume |
| `o` | $0.015/1K tokensgpt-4 | Complex pages, better accuracy |
| `gpt-4` | $0.03/1K tokens | Most complex pages |

### Confidence Threshold

The `confidence_threshold` determines when extraction results are accepted:

- **0.8+**: Strict validation, may trigger more fallbacks
- **0.5-0.7**: Balanced (recommended starting point)
- **0.3-0.5**: Lenient, accepts partial data

## Actions

### ai_extract

Extracts structured data from URLs using AI. This is the primary AI action.

```yaml
- action: "ai_extract"
  params:
    # Task description for the AI
    task: "Extract product details from this page"
    
    # Schema defines expected fields (optional)
    schema:
      name: str
      brand: str
      price: str
      description: str
    
    # Number of search results to visit (if ai_search used)
    visit_top_n: 1
    
    # Maximum agent steps
    max_steps: 15
    
    # Confidence threshold
    confidence_threshold: 0.8
```

**Result Storage:**

- `ctx.results["ai_extract_results"]` - Array of successful extractions
- `ctx.results["ai_extract_failures"]` - Array of failed URLs with errors
- `ctx.results["ai_extract_cost"]` - Cost summary object

### ai_search

Searches for product pages using Brave Search API before extraction.

```yaml
- action: "ai_search"
  params:
    # Search query (supports template variables)
    query: "{sku} {brand} product"
    
    # Maximum results to return
    max_results: 5
```

**Result Storage:**
- `ctx.results["ai_search_results"]` - Array of search results with url, title, description

### ai_validate

Validates AI-extracted data against requirements.

```yaml
- action: "ai_validate"
  params:
    # Required fields that must be present
    required_fields:
      - name
      - price
      - brand
    
    # Whether to validate extracted SKU matches query
    sku_must_match: true
    
    # Minimum confidence threshold
    min_confidence: 0.7
```

**Result Storage:**
- `ctx.results["validation_passed"]` - Boolean pass/fail
- `ctx.results["validation_errors"]` - Array of error messages
- `ctx.results["validation_report"]` - Full validation report

## Complete Example

Here's a full YAML configuration for an AI-powered product scraper:

```yaml
name: "pet-food-ai-extractor"
display_name: "AI Pet Food Extractor"
base_url: "https://example.com"
scraper_type: "agentic"

ai_config:
  tool: "browser-use"
  task: "Extract pet food product information"
  max_steps: 10
  confidence_threshold: 0.7
  llm_model: "gpt-4o-mini"
  use_vision: true
  headless: true

workflows:
  # Step 1: Search for product
  - action: "ai_search"
    name: "find_product"
    params:
      query: "{sku} {brand} official site"
      max_results: 5
  
  # Step 2: Extract from top result
  - action: "ai_extract"
    name: "extract_product"
    params:
      task: "Extract product name, brand, price, description, and images"
      visit_top_n: 1
      schema:
        name: str
        brand: str
        price: str
        description: str
        images: list
      confidence_threshold: 0.75
  
  # Step 3: Validate results
  - action: "ai_validate"
    name: "validate"
    params:
      required_fields:
        - name
        - price
      sku_must_match: true
      min_confidence: 0.7

timeout: 60
retries: 2

test_skus:
  - "12345"
  - "ABC-67890"
```

## Fallback System

The system implements automatic fallback when AI extraction fails:

```
AI Extraction → Traditional CSS → Manual Queue
     ↓               ↓              ↓
  Success?       Success?      Human review
```

### Fallback Triggers

Fallback occurs automatically when:

1. **High Cost**: Extraction exceeds `$0.15` per page
2. **Low Confidence**: Result below `confidence_threshold`
3. **Anti-Bot Detection**: CAPTCHA or blocking detected
4. **Repeated Failures**: Circuit breaker threshold reached

### Circuit Breaker

The circuit breaker prevents repeated failures:

```python
# Default thresholds
CIRCUIT_BREAKER_THRESHOLD = 3  # consecutive failures
MAX_COST_PER_PAGE = 0.15        # USD hard limit
```

When a scraper hits the circuit breaker, it automatically falls back to traditional CSS extraction for a cooling-off period.

### Manual Fallback Configuration

```yaml
fallback_config:
  max_cost_per_extraction: 0.15
  max_attempts_per_tier: 2
  auto_fallback: true
```

## Cost Management

### Tracking Costs

Each AI extraction is tracked with:

```python
from scrapers.ai_cost_tracker import AICostTracker

tracker = AICostTracker()
extraction = tracker.track_extraction(
    input_tokens=1000,
    output_tokens=500,
    model="gpt-4o-mini"
)
print(f"Cost: ${extraction.cost_usd:.4f}")
```

### Cost Limits

The system enforces these limits:

| Limit | Default | Description |
|-------|---------|-------------|
| `MAX_COST_PER_PAGE` | $0.15 | Hard limit triggering fallback |
| `COST_WARNING_THRESHOLD` | $0.10 | Warning alert threshold |
| `CIRCUIT_BREAKER_THRESHOLD` | 3 | Failures before circuit opens |

### Viewing Costs

Access cost data in your results:

```python
# After ai_extract runs
cost_summary = ctx.results["ai_extract_cost"]
print(f"Total: ${cost_summary['total_cost_usd']}")
print(f"Average: ${cost_summary['average_cost_usd']}")
print(f"Max: ${cost_summary['max_cost_usd']}")
```

## Monitoring

### Prometheus Metrics

AI scrapers expose Prometheus-compatible metrics:

```
ai_extraction_count         # Total extractions
ai_extraction_success       # Successful extractions  
ai_extraction_failure       # Failed extractions
ai_success_rate            # Current success rate
ai_cost_total              # Total cost in USD
ai_fallback_count          # Fallback events
ai_site_extractions       # Per-site counts
ai_site_success_rate       # Per-site success rates
ai_circuit_breaker_active # Circuit breaker status
```

Access via:

```python
from scrapers.ai_metrics import get_metrics_collector

collector = get_metrics_collector()
metrics = collector.get_metrics()
prometheus_output = collector.get_prometheus_metrics()
```

### Alerts

The metrics system generates alerts for:

- **High Cost**: Cost exceeds `$0.10` per page
- **Low Success Rate**: Rate drops below 70%
- **Repeated Failures**: 3+ consecutive failures
- **Anti-Bot Blocked**: CAPTCHA/challenge detected

## Troubleshooting

### Common Issues

#### 1. "OPENAI_API_KEY not set"

**Problem**: API key not configured.

**Solution**:
```bash
# Add to your .env file
OPENAI_API_KEY=sk-your-key-here
```

#### 2. "Cost exceeded budget"

**Problem**: Extraction cost exceeded `$0.15` limit.

**Solutions**:
- Lower `max_steps` to reduce agent iterations
- Use `gpt-4o-mini` instead of `gpt-4o`
- Reduce `visit_top_n` to process fewer URLs
- Lower `confidence_threshold` to accept results faster

#### 3. "Low confidence" warnings

**Problem**: AI extraction confidence below threshold.

**Solutions**:
- Improve task description with more specific instructions
- Increase `max_steps` for complex pages
- Enable `use_vision: true` for image-heavy sites
- Add selectors as hints in the config

#### 4. Anti-bot blocks (CAPTCHA)

**Problem**: Site detects automated access.

**Solutions**:
```yaml
anti_detection:
  enabled: true
  user_agent_rotation: true
  request_delay: 2.0  # Increase delay
```

- Enable anti_detection settings
- Add delays between requests
- Consider using residential proxies
- Set `headless: false` for debugging

#### 5. "Could not parse structured JSON"

**Problem**: AI returned non-JSON response.

**Solutions**:
- Simplify the extraction task description
- Provide more explicit schema
- Lower confidence threshold as fallback will use partial data

#### 6. Circuit breaker activated

**Problem**: Too many consecutive failures.

**Solutions**:
- Check logs for root cause
- The system auto-resets after successful extraction
- Manually reset:
```python
from scrapers.ai_cost_tracker import AICostTracker
tracker = AICostTracker()
tracker.reset_circuit_breaker("scraper_name")
```

### Debug Mode

Run with visible browser for debugging:

```yaml
# In your config
ai_config:
  headless: false

# Or via environment
HEADLESS=false
```

Or set in workflow:

```yaml
- action: "ai_extract"
  params:
    task: "Extract product data"
    headless: false
```

## Migration Guide

### Converting Static to AI Scraper

1. **Update scraper_type**:
```yaml
# Before
scraper_type: "static"

# After
scraper_type: "agentic"
```

2. **Add ai_config**:
```yaml
ai_config:
  tool: "browser-use"
  task: "Extract product information"
  llm_model: "gpt-4o-mini"
```

3. **Replace selectors with actions**:
```yaml
# Before (static)
selectors:
  - name: "product_name"
    selector: "h1.title"

# After (AI)
workflows:
  - action: "ai_extract"
    params:
      task: "Extract product name"
```

4. **Add confidence threshold**:
```yaml
ai_config:
  confidence_threshold: 0.7
```

### Hybrid Approach

You can mix AI and traditional extraction:

```yaml
workflows:
  # Use AI for hard-to-scrape pages
  - action: "ai_extract"
    params:
      task: "Extract product details"
      confidence_threshold: 0.8
  
  # Fallback to traditional for simple fields
  - action: "extract"
    params:
      fields:
        - name: "sku"
          selector: "[data-sku]"
```

## Performance Optimization

### Cost Optimization

1. **Use gpt-4o-mini for simple tasks**:
```yaml
llm_model: "gpt-4o-mini"
```

2. **Limit max_steps**:
```yaml
max_steps: 5  # Instead of default 10
```

3. **Reduce visit_top_n**:
```yaml
visit_top_n: 1  # Instead of 3+
```

4. **Set appropriate confidence threshold**:
```yaml
confidence_threshold: 0.6  # Accept earlier
```

### Speed Optimization

1. **Enable headless mode** (default):
```yaml
headless: true
```

2. **Use caching**:
```python
# ai_search results are cached automatically
```

3. **Batch processing**:
```python
from scrapers.ai_discovery import AIDiscoveryScraper

scraper = AIDiscoveryScraper()
results = await scraper.scrape_products_batch(
    items=[{"sku": "123", ...}],
    max_concurrency=4
)
```

### Typical Costs

| Scenario | Model | Estimated Cost |
|----------|-------|----------------|
| Simple product page | gpt-4o-mini | $0.01-0.03 |
| Complex page | gpt-4o-mini | $0.03-0.05 |
| Complex page | gpt-4o | $0.05-0.15 |
| Multi-step extraction | gpt-4o | $0.15-0.30 |

## Best Practices

1. **Start with gpt-4o-mini** - Upgrade to gpt-4o only if needed

2. **Set appropriate confidence** - Start at 0.7 and adjust based on results

3. **Use ai_search first** - Helps AI find the right page

4. **Add validation step** - Always validate critical fields

5. **Monitor costs** - Check ai_extract_cost after each run

6. **Test with edge cases** - Add fake_skus and edge_case_skus to config

7. **Use anti_detection** - Enable for sites with bot protection

8. **Provide schema hints** - Even for AI, hints improve accuracy

## File Reference

| File | Purpose |
|------|---------|
| `scrapers/ai_cost_tracker.py` | Cost tracking and budget enforcement |
| `scrapers/ai_metrics.py` | Metrics collection and Prometheus export |
| `scrapers/ai_discovery.py` | Standalone AI discovery scraper |
| `scrapers/ai_fallback.py` | Fallback chain manager |
| `scrapers/ai_retry.py` | Retry logic for AI actions |
| `scrapers/actions/handlers/ai_base.py` | Base class for AI actions |
| `scrapers/actions/handlers/ai_extract.py` | AI extraction action |
| `scrapers/actions/handlers/ai_search.py` | AI search action |
| `scrapers/actions/handlers/ai_validate.py` | AI validation action |
| `scrapers/configs/ai-template.yaml` | AI scraper template |
