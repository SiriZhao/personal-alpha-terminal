# ROUND 14 - PIT Feature/Outcome-Separated Research Dataset

Date: 2026-08-14

Verdict: `ROUND14_READY` (research SHADOW dataset; no production influence)

## Scope

ROUND14 closes the previously missing feature/outcome-separated dataset. It
builds immutable research artifacts from the existing Round 13 SEC/DeepSeek
feature files and the existing market price database, using the same exchange
session clock as the PIT event-study engine. It never reads an outcome whose
market session close is later than the requested dataset cutoff.

The Classical Quant Core, Alpha, Factor, Probability, Portfolio, Risk,
OperationalPolicy, and execution semantics were not changed. LLM production
influence remains `NONE / 0`. Automatic execution remains disabled.

## Implemented

- `src/personal_alpha_terminal/intelligence/round14_dataset.py`
  - New PIT feature/outcome dataset builder.
  - Maps feature availability to the last completed XNYS session.
  - Computes asset, benchmark, and abnormal returns at 1/3/5/10/20 session
    horizons.
  - Marks outcomes `OUTCOME_PENDING` when their close is after the cutoff.
  - Explicit statuses for missing timestamps, missing prices, no baseline,
    right censoring, and invalid prices.
  - Writes immutable JSON outcome artifacts with deterministic dataset hash.
- `src/personal_alpha_terminal/terminal/intelligence_cli.py`
  - Added `python main.py intelligence outcomes`.
  - Loads the latest real research feature artifact by default.
  - Supports `--dataset-id` and `--cutoff`.
  - Reads real `AAPL`/`SPY` price rows from the existing database.
- `src/personal_alpha_terminal/terminal/cli.py`
  - Registered the `intelligence outcomes` subcommand.
- `tests/unit/intelligence/test_round14_dataset.py`
  - Added PIT visibility, future-outcome exclusion, missing-price, immutable
    artifact, and CLI registration tests.

## Real evidence

Latest real feature dataset:

- feature dataset id:
  `1a18f8b12516d75f1e8b445403e0beb14c88040f81248a363a00b2fc282fd065`
- current cutoff `2026-08-13T16:35:59+00:00`:
  - outcome rows: 75
  - `OUTCOME_READY`: 75
  - `OUTCOME_PENDING`: 0
  - dataset hash: `7d7bfd501bc30dc9275801ec6c498f381357d09822473ad86d32bf254a2d7eb7`
- historical cutoff `2025-03-04T00:00:00+00:00`:
  - outcome rows: 75
  - `OUTCOME_READY`: 15
  - `OUTCOME_PENDING`: 60
  - dataset hash: `fa6b4ab0832e4a421760c458bf225e4e26ccdf12aea22dfd883a9e4598667992`

The historical cutoff proves that future outcomes were excluded: only 15 rows
were visible at the early cutoff, while the same 75-row feature set is fully
visible at the current cutoff.

## Quality gates

- Full pytest: `952 passed`
- `quant_critical`: `31 passed`
- ROUND14 focused tests: `5 passed`
- Ruff: `All checks passed`
- Strict mypy: `Success: no issues found in 418 source files`
- Secret scan: `SECRET_SCAN_PASS`
- `intelligence audit`: raw immutability, PIT certification, identity,
  evidence spans, LLM lineage, future leakage, and zero production influence
  all passed.

## Safety

- Dataset status: `RESEARCH_LIMITED_SURVIVORSHIP`
- Production influence: `NONE`
- Future outcomes read during build: `False`
- OperationalPolicy: unchanged and still awaiting explicit user renewal.
- No broker API, no automatic execution, no LLM trade authority.
