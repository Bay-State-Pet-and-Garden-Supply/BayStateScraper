# Baseline Analysis: AI Discovery Prompt v1

## Scope
- Baseline file: `BayStateScraper/tests/results/results_baseline.json`
- Ground truth: `BayStateScraper/tests/fixtures/test_skus_ground_truth.json`
- SKU count analyzed: **10 / 10**

## Method
- Matched records by `sku`.
- Compared these fields: `brand`, `name`, `price`, `description`, `images`, `availability`.
- Matching rules used for this analysis:
  - **brand**: normalized exact match
  - **name**: normalized exact match
  - **price**: numeric equality after parsing (e.g. `$14.45` -> `14.45`)
  - **description**: token-overlap threshold (to allow paraphrase)
  - **images**: pass if extracted image URLs include a ground-truth source domain
  - **availability**: normalized `in stock` equivalence

## Accuracy Results (Baseline v1)

| Field | Correct | Accuracy | Target | Gap |
|---|---:|---:|---:|---:|
| Brand | 10/10 | **100%** | 90% | +10% |
| Name | 7/10 | **70%** | 85% | -15% |
| Price | 1/10 | **10%** | 80% | -70% |
| Description | 6/10 | **60%** | 70% | -10% |
| Images | 3/10 | **30%** | 90% | -60% |
| Availability | 3/10 | **30%** | 75% | -45% |

### Quick read
- Strong: **brand inference**.
- Weakest: **price, images, availability**.
- Name accuracy is below threshold and driven by variant/size mismatch.

## Failure Patterns

### 1) Source selection frequently chose retailer pages that are hard to extract from
Evidence:
- `www.lowes.com` selected for 2 SKUs (`032247886598`, `032247885591`) and both returned mostly empty non-brand fields.
- `www.homedepot.com` selected for `032247279048` with similarly sparse extraction.

Impact:
- Major field misses (price/description/images/availability) cluster on retailer PDPs.

Likely root cause:
- Source ranking prompt appears to overweight “relevance” without strong penalties for anti-bot walls / dynamic rendering / incomplete visible metadata.

---

### 2) Extraction prompt under-specifies required completion for non-brand fields
Evidence:
- Empty value counts in baseline output:
  - price empty: 6/10
  - availability empty: 6/10
  - description empty: 3/10
  - images empty: 3/10
- Yet all rows are marked `success: true`.

Impact:
- Pipeline records successful runs even when critical commercial fields are missing.

Likely root cause:
- Prompt likely allows early completion once product identity is found, with no strict “required field extraction checklist” before finishing.

---

### 3) Name normalization/variant handling is weak (size/color mismatch)
Evidence:
- `032247278140`: extracted `Miracle-Gro Potting Mix` vs ground truth `Miracle-Gro Potting Mix 25 Quart`.
- `032247884594`: extracted generic Nature Scapes mulch name while ground truth requires `Sierra Red` variant.
- `095668225308`: extracted `MannaPro All Flock 16% Crumbles w/Probiotics [8 lb]` (close semantically, but not canonical name format).

Impact:
- Brand can be correct while SKU-specific product identity remains inaccurate.

Likely root cause:
- Prompt does not force verification that extracted name includes key disambiguators (size, color, variant terms).

---

### 4) Image extraction is often irrelevant or non-canonical
Evidence:
- `095668225308` sourced from `armoranimalhealth.com` and returned retailer image URL instead of canonical brand domain.
- `095668302580` included many gallery/variant images from multiple flavors, not SKU-focused image set.

Impact:
- Image field quality is noisy and often not tied to exact SKU/variant.

Likely root cause:
- Prompt lacks constraints to prefer primary hero image(s) for exact variant and to prioritize manufacturer CDN assets.

---

### 5) Availability extraction semantics are inconsistent
Evidence:
- Multiple blanks even when pages likely expose stock state.
- One conflicting outcome: `032247884594` extracted `Out Of Stock` while ground truth expects `In Stock` (potential source/date mismatch + no recency guardrails).

Impact:
- Availability reliability is low and unstable for operational use.

Likely root cause:
- Prompt does not define strict extraction precedence (e.g., explicit stock badge > add-to-cart state > fallback unknown), nor timestamp/source confidence handling.

## SKU-level highlights
- **Best quality extraction:** `032247761215` (Scotts spreader), `032247278140` (good descriptive content but missed exact name/price/images match criteria).
- **Most degraded extractions:** `032247886598`, `032247885591`, `032247279048`, `032247884594` (multi-field misses).
- **No total failures:** 10/10 marked success, but semantic completeness is far below required thresholds.

## Root Cause Summary
1. **Source selection error class**: retailer-heavy choices for SKUs where official/manufacturer pages or cleaner pages were preferable.
2. **Extraction completion error class**: no strict enforcement of required fields before returning success.
3. **Variant disambiguation error class**: name/image extraction not anchored to exact SKU attributes (size/color/form).
4. **Availability interpretation error class**: weak normalization and lack of recency/confidence handling.

## Prompt v2 Recommendations (for crawl4ai)

The next iteration should focus on crawl4ai extraction instructions, Brave query tuning, and crawl configuration.

1. **Brave query templating with SKU anchors (high priority)**
   - Query format: `"{brand_or_inferred_brand} {sku} {normalized_product_terms}"` plus fallback without brand.
   - Add negative terms to suppress low-quality aggregator pages.
   - Expected gain: better source precision for exact SKU pages.

2. **Source-ranking rubric in prompt with explicit domain tiers**
   - Tier 1: manufacturer/official brand domains.
   - Tier 2: major trusted retailers (only if Tier 1 unavailable).
   - Tier 3: marketplaces/affiliate pages (last resort).
   - Require model to output **why** a URL was selected and confidence score.

3. **crawl4ai multi-candidate preflight before final extraction**
   - Fetch top 3 candidates and run a lightweight precheck for:
     - presence of SKU or near-match product identifiers,
     - visible price selector/text,
     - stock indicator presence,
     - image asset availability.
   - Select candidate with best precheck score.

4. **Hard extraction checklist in prompt (must-fill policy)**
   - Enforce required fields: `name`, `price`, `availability`, at least 1 `image`.
   - If missing, instruct crawl4ai to continue navigation or alternate candidate rather than returning success.
   - Return `success=false` with explicit missing fields if unresolved.

5. **Canonical name rules with variant locking**
   - Prompt instruction: product name must include key disambiguators (size/weight, color, form factor) when present.
   - Add post-extraction validation: compare extracted name tokens vs SKU input tokens and require minimum overlap.

6. **Price extraction normalization policy**
   - Accept only current sale/base price from product page context.
   - Strip currency symbols, normalize numeric value, reject placeholders (`Not specified`, empty).
   - If range/multi-pack appears, choose single-unit PDP price or mark ambiguous.

7. **Image quality/precision constraints**
   - Prefer primary hero image for exact variant first; cap to top 3 relevant images.
   - Prioritize manufacturer CDN or PDP image URLs.
   - Reject images clearly tied to different flavor/variant carousel items unless variant matches.

8. **Availability extraction precedence + normalization**
   - Precedence: stock badge text > add-to-cart enabled state > structured data (`availability`) > fallback `unknown`.
   - Normalize to controlled set: `In Stock | Out of Stock | Limited | Unknown`.

9. **crawl4ai configuration tuning for dynamic pages**
   - Increase wait strategy for dynamic retailer PDPs (network-idle + targeted element waits).
   - Enable retry with alternate render strategy when key nodes are missing.
   - Capture minimal DOM snapshot used for extraction for auditability.

10. **Introduce extraction confidence decomposition**
   - Separate scores for source confidence, field completeness, and variant match confidence.
   - Use this to gate fallback to next source candidate.

## Priority Fix Plan
1. First fix **source selection + mandatory field completion** (largest gap: price/images/availability).
2. Then fix **variant locking** for name/image precision.
3. Finally tune **dynamic-page crawl behavior** and confidence gating.

## Conclusion
Baseline Prompt v1 demonstrates strong brand inference but does not meet operational thresholds for commercial fields. The dominant failure mode is not total run failure; it is **silent partial extraction**. Prompt v2 for crawl4ai should enforce strict source-quality selection and required-field completion before success is returned.
