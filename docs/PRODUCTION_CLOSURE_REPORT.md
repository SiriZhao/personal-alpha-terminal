# Production Closure Report

Date: 2026-08-11

Verified implementation baseline: `80f1739` (`fix: close production signal and certification pipeline`).

## Classification

**NON_ACTIONABLE / FAIL CLOSED.** The daily dataset is certified for current analysis, but the strategy has no real immutable production approval backed by survivorship-safe historical PIT data and locked OOS, walk-forward, after-cost evidence. No approval was manufactured.

## Root causes and fixes

- Alpha candidates are deterministic outputs of `USAdaptiveAlphaCoreV1`. All real candidates were `DIAGNOSTIC_ONLY` because the model approval registry and validation-artifact directory contain no valid production record. Current live-universe history is explicitly not survivorship-safe for historical backtesting.
- Production approval remains bound to parameter identity and a versioned historical validation manifest. Daily data refresh versions no longer incorrectly invalidate a valid historical approval. Probability calibration is a separate optional artifact and no longer gates or weights deterministic alpha.
- Data Health previously reused the overall run gate, so a later SIGNAL failure turned certified DATA/PIT/universe rows into false failures and erased their identities. Data Certification, Data Health, pipeline, summary, and run certificate now derive from one authorization status and carry snapshot/version/hash identity.
- A single existing ledger was previously selected implicitly. Daily runs now require explicit `portfolio_id`; this prevents a fixture or stale ledger from being treated as the user's portfolio.

## Evidence chain

Each run certificate includes run/analysis/trade dates, PIT cutoff, config hash, data snapshot and content hash, research/universe versions, strategy/factor/signal versions, production approval and optional probability artifact IDs, portfolio snapshot ID, stage statuses, blockers, transaction-cost assumptions, classification, and stable canonical input/result hashes. ML is reported as `NOT_REQUIRED`; LLM/regime absence is optional rather than a core-data failure.

## Strategy certification

`quant_engine.strategy_certification` provides a reproducible fail-closed evaluator for temporal splits, at least 252 locked OOS sessions, walk-forward folds, future-row/PIT controls, survivorship and corporate actions, same-PIT SPY/QQQ benchmarks, commissions/spread/slippage/impact, net performance, turnover, drawdown, concentration, and stability. Only complete passing evidence yields a versioned `PRODUCTION_APPROVED` artifact identity.

## Test and E2E result

- Static lint: `ruff check src tests` passed.
- Full suite: **586 passed** in 68.24 seconds; no skip/xpass was added to manufacture success.
- E2E A: uninitialized/unselected portfolio completes the data/research chain, produces zero trades, and blocks at strategy/portfolio as applicable.
- E2E B: isolated cash/portfolio fixture proves approved-artifact plumbing through portfolio, risk, and decision; removing approval fails closed. Fixture approval is not real production evidence.
- Reproducibility: two equivalent real local runs produced identical canonical input hash `245ad85f...c5b6` and result hash `611cfc27...ef32`; both classified `INVALID_NON_ACTIONABLE` with zero actions.

## Remaining blockers

1. Acquire and certify survivorship-safe historical universe membership, delistings, corporate actions, and PIT total-return history.
2. Run the locked OOS/walk-forward certification using real data and only register its artifact if every gate passes.
3. The user must verify/create a manual ledger and explicitly select `portfolio_id`.

The documentation commit and remote branch are recorded in the final handoff after push.
