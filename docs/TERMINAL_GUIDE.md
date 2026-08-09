# Terminal Guide

## First launch

Double-click `PersonalAlphaTerminal.exe`. The application creates `%LOCALAPPDATA%\PersonalAlphaTerminal` and a local SQLite database. It does not open a browser or localhost service. No AI key is required.

If no real portfolio exists, the result is intentionally non-actionable. Create one:

```text
PersonalAlphaTerminal.exe portfolio-init --name "My Portfolio" --cash 100000
PersonalAlphaTerminal.exe portfolio
```

## Charles Schwab CSV import

The importer validates headers, encoding, symbols, positive quantities, cost values, duplicates, and cash rows. It never edits the source CSV and never invents an unknown security.

```text
# Preview and validate only
PersonalAlphaTerminal.exe portfolio-import schwab.csv --portfolio-id 1 --as-of 2026-08-08

# Commit the reviewed snapshot
PersonalAlphaTerminal.exe portfolio-import schwab.csv --portfolio-id 1 --as-of 2026-08-08 --commit
```

Unmatched symbols remain excluded and are reported. A Schwab position export is a holdings snapshot, not transaction history.

## Daily report

The no-argument executable and `daily` command run the same application orchestrator. Sections are ordered by evidence flow:

- **HEADER** — version, ET time, analysis/trade dates, run ID, data cutoff.
- **PIPELINE** — PASS/WARN/FAIL/SKIPPED for Calendar, Data, PIT, Feature, Factor, Signal, Probability, Portfolio, Risk, Decision, Execution, and Persistence.
- **DATA HEALTH** — expected/latest dates, coverage, missingness, source, freshness, PIT status.
- **MARKET REGIME** — only deterministic outputs available to the run; an uncalibrated score is not called a probability.
- **PORTFOLIO** — cash, positions, weights, target deltas, exposure and valuation completeness.
- **FACTOR / ALPHA** — inputs actually used by the registered strategy. `CANDIDATE != TRADE`.
- **CONDITIONAL PROBABILITY** — conditional/base rates, lift, sample size, interval and OOS/calibration status. Small samples show `INSUFFICIENT EVIDENCE`.
- **RISK / STRESS** — raw target versus risk-adjusted target, causal recent-versus-baseline
  correlation, size-validation state, concentration, turnover, stress vetoes and warnings.
- **REJECTED SIGNALS** — which gate rejected an intermediate proposal and why.
- **FINAL VALIDATED DECISIONS** — the only formal decision output; copied directly from the persisted `DailyQuantResult`.
- **EXECUTION PLAN** — sells/reductions before buys/increases, estimated costs and cash; manual execution only.
- **BENCHMARK** — only metrics supported by adequate, aligned observations.

The distinctions are mandatory:

- Candidate ≠ Trade
- Signal ≠ Decision
- Probability ≠ Certainty
- LLM ≠ Quant Engine

## Manual decision and fill workflow

```text
PersonalAlphaTerminal.exe accept <recommendation_id> --run-id <run_id> --reason "reviewed"
PersonalAlphaTerminal.exe reject <recommendation_id> --run-id <run_id> --reason "tax constraint"
PersonalAlphaTerminal.exe watch <recommendation_id> --run-id <run_id>
```

ACCEPT produces `PENDING MANUAL EXECUTION`; it does not change holdings. After a real Schwab fill:

```text
PersonalAlphaTerminal.exe mark-executed <recommendation_id> --run-id <run_id> --fill-id schwab-fill-001 --price 187.25 --quantity 4 --fees 0
PersonalAlphaTerminal.exe mark-executed <recommendation_id> --run-id <run_id> --fill-id schwab-fill-002 --price 187.40 --quantity 6 --fees 0
```

The first fill above leaves a ten-share recommendation `PARTIAL`; the second makes it `FILLED`.
Duplicate fill IDs are idempotent only when the complete payload is identical. Cumulative fills
cannot exceed the approved quantity, buys cannot exceed cash, and sells cannot exceed holdings.
The timestamp must be eligible and price/quantity/fees must be valid.

```text
PersonalAlphaTerminal.exe modify-execution <recommendation_id> --run-id <run_id> --quantity 8 --reason "manual size reduction"
PersonalAlphaTerminal.exe cancel-execution <recommendation_id> --run-id <run_id> --reason "order cancelled at Schwab"
```

Modification cannot increase the original approved quantity or go below already filled quantity.
Neither modification nor cancellation reverses fills that already changed the real ledger.

## Other commands

- `refresh`: refresh market data, then run daily.
- `data`, `factors`, `probability`, `risk`, `decisions`: read the latest persisted immutable run. They never execute the pipeline. Add `--run-id <id>` to inspect history; when no run exists they return `NO_PERSISTED_RUN`.
- `backtest`: show/run the PIT-gated production backtest capability; a blocked gate lists missing evidence.
- `research`: run research workflow, never an execution bypass.
- `doctor` / `diagnostics`: check configuration, database/migration, storage, calendar, portfolio, broker and optional AI state.
- `settings`: show resolved effective values plus stable runtime/root hashes, not raw YAML text.

Decision Trace uses `NOT_CAPTURED` when a real intermediate (for example winsorized values or a pre-risk target) was not persisted. It never copies a normalized value into a raw field or a post-risk target into a pre-risk field.

## Safety behavior

Stale data, failed PIT validation, missing portfolio, invalid covariance/risk/stress results, an
unavailable production calendar, or unapproved models result in `NOT_ACTIONABLE`. Diagnostic
factor tables may still appear, but no BUY/SELL may enter the execution plan. `NO_ACTION` is
reserved for a fully completed chain that computes no rebalance.
