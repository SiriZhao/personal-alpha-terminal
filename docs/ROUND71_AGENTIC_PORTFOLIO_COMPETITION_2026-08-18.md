# ROUND71 — Agentic Portfolio Competition (2026-08-18)

## Scope and verdict

- Starting SHA: `a47b8b1559b3efe046df04dacf3b4452e9af404c`
- Final SHA: recorded by the dedicated ROUND71 commit (`git show -s --format=%H HEAD`)
- Engineering verdict: **PASS_WITH_WARNINGS**.
- Economic verdict: **BLOCKED_INSUFFICIENT_EVIDENCE**; no variant is promoted.
- Current production policy: `PURE_QUANT` remains unchanged.
- Formal LLM influence: `0.0`.
- Formal Probability influence: `0.0`.

ROUND71 adds a synchronized counterfactual tournament. It does not select a
winner, alter the optimizer, change exposure policy, or enable execution.

## Variants

The ledger supports exactly aligned records for:

1. `PURE_QUANT`
2. `QUANT_PLUS_PROBABILITY`
3. `QUANT_PLUS_LLM`
4. `QUANT_PLUS_PROBABILITY_PLUS_LLM`
5. `FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE`

Every `DecisionFreeze` records the same decision timestamp, information cutoff,
universe identity, benchmark, executable-price assumptions, transaction-cost
model, accounting rules, model/config hashes, target weights, target exposure,
risk-adjustment hash, and evidence class. A tournament rejects duplicate
variants or any alignment mismatch.

## Decision freeze and persistence

`DecisionFreeze` and `TournamentDecision` are content-hashed and immutable.
Reusing a decision ID with changed targets or inputs raises an error. Outcomes
cannot be attached to an unknown variant, cannot precede the decision, and
cannot be rewritten after append.

`PortfolioCompetitionLedger` provides append-only JSONL persistence plus a
deterministic replay document. Missing, partial, and complete outcomes are
distinct. Benchmark-unavailable outcomes cannot carry a benchmark return.

## Attribution semantics

The evaluator pairs each challenger with the same `PURE_QUANT` decision and
computes deltas for:

- return and benchmark excess return;
- upside and downside capture;
- drawdown and volatility-related risk-adjusted return;
- turnover and expected cost.

Layer attribution is explicit:

- `PROBABILITY_VALUE_ADD`
- `LLM_VALUE_ADD`
- `EXPOSURE_CONTROLLER_VALUE_ADD`
- reserved `SELECTION_VALUE_ADD`, `RISK_CONTROLLER_VALUE_ADD`, and `COST_IMPACT`

Historical research and synthetic stress are never included in promotion
sample counts. Forward shadow, paper, and live evidence remain separate in each
outcome record and are not collapsed into one confidence number.

## Promotion and demotion rules

A challenger can only be `PROMOTE` when the configured minimum complete sample
and unique-session counts pass, evidence is forward/paper/live, and return,
excess return, drawdown, turnover, upside capture, and downside protection
constraints pass. For paired samples of at least two observations it records a
deterministic 95% normal-approximation interval; with fewer observations the
interval remains unavailable and no confidence is invented.

With insufficient or non-promotable evidence, the verdict is
`BLOCKED_INSUFFICIENT_EVIDENCE` or `BLOCKED_DATA_QUALITY`. A currently active
variant that later fails the same gates becomes `DEMOTE_TO_SHADOW`; promotion
is therefore reversible rather than one-way.

## Current leader

No statistically defensible leader exists. `PURE_QUANT` is the current
production scheme because it is the existing policy champion, not because this
round established superior economic performance. With no sufficient aligned
forward sample, the terminal reports **证据积累中** rather than fake gains or
winner percentages.

## Terminal

The hybrid intelligence renderer now exposes a compact `【智能决策竞争】`
section with current production, strongest challenger, Quant/Probability/LLM/
adaptive-exposure gains, evidence sample size, promotion condition, and formal
influence values. Missing evidence is shown as `证据积累中`.

## QA

- Focused ROUND71 + existing agentic/exposure/tournament/terminal tests:
  **36 passed** in the main focused run; the added ROUND71 renderer/ledger
  subset also passed.
- Ruff on changed modules/tests: **PASS**.
- Strict mypy on changed modules: **PASS**.
- Full-package mypy: **BLOCKED** by missing `exchange_calendars` (12 errors in
  existing calendar imports).
- Quant-critical pytest: **BLOCKED during collection** by missing
  `exchange_calendars` (23 collection errors; 1222 tests deselected).
- Full pytest: **BLOCKED during collection by the same dependency**; existing
  Windows `.pytest_cache` ACL warnings were also observed.
- Secret scan: **SECRET_SCAN_PASS**.

Inherited dirty files from ROUND70 were preserved and excluded from the ROUND71
commit.
