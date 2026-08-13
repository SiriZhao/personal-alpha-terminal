# ROUND 14 - LLM Quant Feature Alpha Research & Locked-OOS Validation

Date: 2026-08-14

Verdict: `ROUND14_LLM_ALPHA_NOT_PROVED`

## Executive conclusion

The ROUND14 protocol is implemented and executed on the real current corpus.
The result is a legal, evidence-backed non-proof: the available SEC/PIT/LLM
dataset is far too small and too single-issuer to establish after-cost,
out-of-sample incremental alpha. No promotion candidate was generated and no
production influence was enabled.

The Classical Quant Champion was frozen through the existing strategy factor
audit identity. The cost model was frozen to `us-daily-cost-v1`. All
experiments are defined against the same champion.

## Corpus limitation

Current real corpus evidence:

- SEC raw documents: 44
- PIT-certified documents: 44
- issuer-resolved documents: 44
- security-mapped documents: 24
- accepted events: 18
- ROUND14 outcome rows: 75
- issuers: 1
- tickers: 1
- LLM features: 15
- corpus status: `RESEARCH_LIMITED_SURVIVORSHIP`

This is engineering evidence, not alpha evidence. The corpus does not cover a
broad cross-section, multiple industries, market-cap buckets, volatility
regimes, or a certified historical universe. It is therefore marked
`RESEARCH_LIMITED_SURVIVORSHIP`; it is not claimed as `FULL_CERTIFIED`.

## Protocol implemented

- Frozen Classical Champion identity:
  `cdca09f0c7faca2e9b20610ff578dc1c22281d0a2f53701c50ead4088c6101f5`
- Frozen transaction cost model: `us-daily-cost-v1`
- PIT outcome separation: outcome files never contain rows whose market close
  is after the dataset cutoff.
- Purged walk-forward and embargo are evaluated through
  `purged_walk_forward_splits`.
- Locked OOS requires 252 observations, 4+ walk-forward folds, and a broad
  cross-section.
- Experiments defined:
  - `A_CLASSICAL_ONLY`: frozen reference
  - `B_CLASSICAL_DETERMINISTIC_SEC`: blocked by insufficient corpus
  - `C_CLASSICAL_LLM_FEATURES`: blocked by insufficient corpus
  - `D_CLASSICAL_SEC_LLM_COMBINED`: blocked by insufficient corpus
- Promotion gate default: `LLM production influence = NONE`.
- No random split was used.

## Real ROUND14 alpha research result

Run ID: `round14-alpha-afa6b79536f6a926`

Blockers:

- `CROSS_SECTION_INSUFFICIENT`
- `LOCKED_OOS_SAMPLE_INSUFFICIENT`
- `RESEARCH_LIMITED_SURVIVORSHIP`
- `WALK_FORWARD_FOLDS_INSUFFICIENT`

Observed descriptive metrics:

- observations: 75
- feature count: 15
- issuer count: 1
- ticker count: 1
- mean abnormal return: -0.0126497
- median abnormal return: 0.0035262
- hit rate: 0.60
- IC / Rank IC / ICIR: not computed because cross-section is invalid
- Net CAGR / Sharpe / Sortino / Calmar / alpha vs SPY / alpha vs QQQ: withheld
- promotion candidate: none

Withholding these metrics is not an omission; it prevents meaningless numbers
from being presented as validation.

## Round15 dataset

A Round15-ready PIT research dataset was generated from the real ROUND14
outcome artifact:

- schema: `round15-research-v1`
- status: `RESEARCH_LIMITED_SURVIVORSHIP`
- production influence: `NONE`
- future outcomes read during build: `False`
- rows: 75

Artifact:

`var/intelligence/sec-edgar/research/round15/1a18f8b12516d75f1e8b445403e0beb14c88040f81248a363a00b2fc282fd065-r14-2026-08-13.json`

## Quality gates

- Full pytest: `956 passed`
- `quant_critical`: `31 passed`
- ROUND14 alpha focused tests: `4 passed`
- Ruff: `All checks passed`
- Strict mypy: `Success: no issues found in 419 source files`
- Secret scan: `SECRET_SCAN_PASS`
- `intelligence audit`: raw/PIT/evidence/LLM lineage/future leakage checks
  remained passing.

## Final disposition

`ROUND14_LLM_ALPHA_NOT_PROVED`

No production influence, no automatic execution, no policy renewal, and no
promotion candidate were generated. The next round should only expand the
corpus when a certified multi-CIK PIT identity/universe manifest is available;
the current data remains research-limited.
