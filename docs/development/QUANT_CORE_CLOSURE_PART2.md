# Quant Core Closure / Phase I Remediation Part 2

Date: 2026-08-09

Branch: `codex/quant-core-closure-part1`

Part 1 implementation commit: `05c3776`

## Closure status

| Area | Status | Evidence |
|---|---|---|
| Executable strategy object | IMPLEMENTED_FIXTURE_TESTED | `USAdaptiveAlphaCoreV1` is registered, deterministic and parameter-fingerprinted. Production approval still requires matching real-data locked OOS evidence. |
| Daily decision computation | IMPLEMENTED_FIXTURE_TESTED | DB assembler -> Alpha -> risk -> portfolio -> trade differences -> immutable `TodayResult`; no hard-coded NO ACTION. |
| Factor contract | IMPLEMENTED_FIXTURE_TESTED | PIT `FactorObservation` captures raw/winsorized/normalized values, coverage, versions and quality status. Existing cross-sectional engine performs winsorization, robust normalization and sector/size controls; existing evaluator reports IC, rank IC, decay, turnover and stability. |
| Conditional evidence | IMPLEMENTED_FIXTURE_TESTED | Beta-Binomial shrinkage, effective N, overlap removal, right censoring, expected-return lift, costs, tail loss, OOS Brier/baseline, drift, freshness and BH-FDR. It cannot create positions. |
| Event study | IMPLEMENTED_FIXTURE_TESTED | Trading-session/PIT cutoff, benchmark abnormal returns, CAR/BHAR, moving-block bootstrap, overlap/right-censor and subperiod/regime checks. Default is RESEARCH_SUPPORT_ONLY. |
| Graph/lead-lag | IMPLEMENTED_FIXTURE_TESTED / RESEARCH_ONLY | Existing adapter requires statistical/economic/OOS/after-cost gates and never claims causality. No production adapter is approved. |
| Experiment governance | IMPLEMENTED_FIXTURE_TESTED | Append-only registry and results, lock-before-test, immutable locked result, purged/embargoed walk-forward, parameter perturbation and deflated Sharpe risk. |
| Regime probability | BLOCKED_BY_DATA | Existing OOS calibration gate remains authoritative. Without a real certified calibration record it is a score, not a probability. |
| Momentum-crash calibration | BLOCKED_BY_DATA | No parameter was changed using locked crisis windows. Crash/V recovery, latency and opportunity-cost exam metrics remain N/A. |
| Portfolio/risk | IMPLEMENTED_FIXTURE_TESTED | Shrunk/PSD covariance, beta/sector/ADV/HHI/turnover controls plus CVaR, liquidity, correlation, gap, volatility, benchmark, single-name and sector stress reporting. Missing metadata fails closed. |
| Transaction costs | IMPLEMENTED_FIXTURE_TESTED | One `TransactionCostModel` includes configurable commission, half spread, slippage, participation impact, minimum fee, regulatory fee and ADV cap. |
| Manual portfolio | IMPLEMENTED_FIXTURE_TESTED | Existing immutable ledger covers deposit/withdrawal/buy/sell/fee/dividend/split/FX; added idempotent broker snapshot reconciliation. ACCEPT still does not change holdings. |
| AI boundary | IMPLEMENTED_FIXTURE_TESTED | Outbound payload is redacted by default, portfolio-sensitive fields require explicit policy change, structured numeric claims can be checked against symbol/date/unit/direction/source evidence. AI cannot affect quant decisions. |
| Runtime/database | IMPLEMENTED_FIXTURE_TESTED | Memory DB is isolated TEST; production/development rebind remains prohibited. Forward-only manual execution evidence revision advances the single head to `b2e3f4a5c6d7`. |
| PIT real historical evidence | BLOCKED_BY_DATA | No certified historical universe/delistings, corporate-action ledger, PIT total-return archive, fundamental revision archive or independent reconciliation. |
| Locked real OOS | BLOCKED_BY_DATA | No untouched locked-OOS experiment on certified real PIT data. |

## Validation

- 504 tests passed in deterministic segmented runs: 421 unit (including 4 optional backend and 7 PostgreSQL backup), 66 integration, 17 dashboard/performance.
- The monolithic pytest command reached the environment's 10-minute limit; segmented runs cover the complete collected test tree.
- Ruff: PASS (whole repository).
- mypy strict: PASS, 392 source files.
- pip check: PASS.
- Alembic: one head, `b2e3f4a5c6d7`; empty/legacy upgrade tests PASS.
- Secret-pattern scan: no hard-coded key/bearer-token match.
- Dependency vulnerability scan: BLOCKED_BY_ENVIRONMENT because `pip-audit` is not installed; no tool was downloaded.
- Phase I exam: executed under source-hash lock; BLOCKED/N/A for all fixed windows because real PIT and locked OOS evidence is absent.

## Product gates

1. A real executable strategy implementation exists: **yes, code and fixture tested**.
2. Daily is quant-computed rather than hard-coded: **yes**.
3. Live data: free-provider display/research prices are available subject to their quality status; not independently PIT-certified.
4. PIT historical certification: **none on real production data**.
5. Fixture tested: factor, conditional evidence, event study, risk, portfolio, cost, daily and backtest contracts.
6. Locked OOS on certified real data: **none**.
7. Shadow Forward: only non-action data collection/diagnostic shadow is appropriate; executable-candidate shadow remains blocked.
8. Small-capital Manual Pilot: **no**.
9. Remaining blockers: historical universe/delistings, corporate actions, PIT total return, fundamental vintages, second-source reconciliation and untouched locked OOS.
10. Known permanent code blocker: **none identified in the authoritative production chain**. External evidence remains intentionally blocking.

Historical and simulated evidence does not guarantee future results. Equity investments can lose principal; risk controls reduce neither market risk nor loss probability to zero.
