# Analysis: AI Discovery Prompt v2

## Scope
- V2 file: `BayStateScraper/tests/results/results_v2.json`
- Ground truth: `BayStateScraper/tests/fixtures/test_skus_ground_truth.json`
- Baseline reference: `BayStateScraper/tests/analysis/analysis_baseline.md`
- SKU count analyzed: **10 / 10**

## Method
- Matched records by `sku`.
- Compared these V2 fields: `brand`, `name`, `description`, `size_metrics`, `images`, `categories`.
- Matching rules used:
  - **brand**: normalized exact match
  - **name**: normalized exact match (`product_name` vs ground-truth `name`)
  - **description**: token-overlap threshold (>= 0.35) to allow paraphrase
  - **size_metrics**: normalized exact match, with empty/unspecified equivalence
  - **images**: pass if at least one extracted image URL shares a domain with a ground-truth image URL
  - **categories**: strict normalized set equality

## Accuracy Results (Prompt v2)

| Field | Correct | Accuracy |
|---|---:|---:|
| Brand | 10/10 | **100%** |
| Name | 7/10 | **70%** |
| Description | 10/10 | **100%** |
| Size Metrics *(new in v2)* | 9/10 | **90%** |
| Images | 4/10 | **40%** |
| Categories *(new in v2)* | 1/10 | **10%** |

## Delta vs V1 Baseline (common fields only)

> Baseline v1 fields used for delta: **Brand, Name, Description, Images**.

| Field | V1 Accuracy | V2 Accuracy | Delta |
|---|---:|---:|---:|
| Brand | 100% | 100% | **+0%** |
| Name | 70% | 70% | **+0%** |
| Description | 60% | 100% | **+40%** |
| Images | 30% | 40% | **+10%** |

## New-field performance introduced by v2
- **Size Metrics:** 90% (9/10) — strong extraction quality on weight/volume/capacity.
- **Categories:** 10% (1/10) — weak under strict canonical matching; outputs are usually related but taxonomy labels differ from ground truth.

## Key observations
1. **Prompt v2 improved targeted catalog extraction overall for common fields**, primarily due to a large gain in description quality and a smaller gain in images.
2. **Brand remains saturated at 100%**; no further gain observed.
3. **Name did not improve**; misses are still mostly variant/canonical-name issues.
4. **Size metrics are successful as a new field** (high hit rate).
5. **Categories are the major weak point** for v2 under strict evaluation and need taxonomy alignment/canonicalization rules.

## Conclusion
Yes — **Prompt v2 improved extraction accuracy for targeted website catalog fields** compared to v1 on the shared metrics (**Description +40 points, Images +10 points, Brand/Name unchanged**), and it added a strong new `size_metrics` capability (**90%**). However, `categories` quality is currently low (**10%**) and is the main area requiring prompt/schema refinement.
