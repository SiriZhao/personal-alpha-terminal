# Quant Engine Core Reconstruction — Part 2

Status: **implemented and fixture-tested; real-data production gate remains blocked**  
Date: 2026-08-08

## Production chain

The deterministic research-to-decision boundary is now:

```text
ResearchDataGate authorization
  -> point-in-time universe and input-time validation
  -> PRODUCTION_APPROVED Alpha with calibrated confidence
  -> shrinkage risk model
  -> dynamic risk budget
  -> constrained portfolio construction
  -> target portfolio
  -> cost-aware trade differences
  -> manual Daily Decision
```

`DailyQuantPipeline` is independent of UI, AI, broker, and paper-trading code. A
critical failure returns `BLOCKED` and no proposals. The application service
exposes this pipeline as the sole production-safe Alpha-to-decision entrypoint;
the older scheduler remains a data/research scheduler and cannot manufacture
target weights.

## Implemented

- Ledoit-Wolf covariance with PSD correction and an explicit diagonal fallback.
- Asset volatility, covariance, correlation, beta, sector, size, ADV, HHI, and
  correlation-cluster exposure controls.
- Long-only constrained optimization with cash, gross, position, sector,
  cluster, volatility, beta, size, HHI, turnover, and liquidity constraints.
- Alpha sizing in annualized expected-excess-return space, including calibrated
  confidence and half-life decay. Multiple signals are confidence-weighted;
  duplicated signals do not mechanically multiply expected return.
- Smooth regime, drawdown, realized-volatility, correlation-spike, and
  concentration risk-budget reductions. An uncalibrated regime score does not
  affect position size.
- A shared transaction-cost model for optimizer, trade generator, and backtest:
  commission, half-spread, slippage, square-root participation impact, and an
  explicit ADV ceiling.
- No-trade band, minimum rebalance threshold, minimum trade value, and turnover
  penalty.
- BUY / INCREASE / REDUCE / SELL / HOLD proposals derived only from current vs.
  optimizer target weights. Automatic execution is always disabled.
- Event-driven raw-price backtest: signal after T close, execution at the next
  verified US session open, prior-session ADV, raw valuation, PIT corporate
  actions, delisting cash, split/dividend accounting, and stale-price blocking.
- Verified XNYS sessions, including holiday rejection and timezone/DST-aware
  market-close checks.
- SPY total-return benchmark lineage and coverage checks. Missing benchmark or
  incomplete historical universe downgrades the run to `RESEARCH_ONLY`.
- Accounting invariants for cash + positions = equity and for realized PnL,
  unrealized PnL, dividends, and transaction costs.
- CAGR, annualized return/volatility, Sharpe, Sortino, Calmar, drawdown and
  duration, turnover, holding period, cost drag, alpha, beta, tracking error,
  information ratio, and up/down capture.
- Symbol, sector, Alpha-source, risk, regime/risk-reduction, and cost attribution
  primitives.
- Chronological TRAIN / VALIDATION / embargo / locked OOS fold construction,
  immutable parameter fingerprints, and robustness assessment for parameter,
  execution-delay, spread, slippage, and rebalance perturbations.
- Immutable run and result hashes covering code/data/model/config/cost/universe/
  benchmark/validation identities and the detailed accounting result.

## Production safety gates

No target or daily proposal is produced when any of the following applies:

- ResearchDataGate does not authorize portfolio decisions.
- PIT flag or universe snapshot is missing.
- Input return history extends beyond the decision time.
- Alpha is not `PRODUCTION_APPROVED`, PIT-valid, current, quality-valid, and
  confidence-calibrated.
- Portfolio model lacks a locked OOS validation manifest ID.
- Covariance, beta, variance, benchmark, metadata, or ADV is invalid.
- Optimizer, transaction-cost validation, or trade generation fails.
- Dynamic risk state blocks new exposure.

There is no equal-weight, ranking-to-weight, QuantScore, or UI fallback in this
path. The legacy equal/inverse-volatility allocator is explicitly research-only.

## Deterministic miniature market

`tests/unit/quant_engine/test_miniature_end_to_end.py` covers a fixed market with:

- multiple securities and sectors;
- an IPO with shorter history;
- delisting cash consideration;
- split and cash dividend;
- an asset-level missing trading day;
- a late fundamental revision that is unavailable at decision time;
- a volatility/regime change;
- factor normalization, Alpha, risk, target portfolio, trades, accounting, and
  Daily Decision.

`tests/fixtures/quant_engine/part2_golden.json` locks target weights, result hash,
manifest hash, ending equity, net return, and trade count.

## Verification

- Part 2 Quant Engine suite: **35 passed**.
- Dashboard + integration: **71 passed**.
- Other unit and performance tests: **288 passed**.
- Total confirmed: **394 passed**.
- Ruff on Quant Engine and tests: **PASS**.
- Mypy strict on all 56 Quant Engine source files: **PASS**.
- `pip check`: **PASS**.
- Environment-blocked: 3 PostgreSQL backup tests (Windows sandbox permits the
  fixture write but denies the immediate read) and 3 VectorBT tests (optional
  backend/JIT path exceeded 120 seconds). These are **not counted as passed**.

## Remaining quant limitations

1. No certified, complete real US historical universe and delisting source is
   present. Real historical results must retain `SURVIVORSHIP_BIAS_RISK`.
2. PIT corporate-action completeness and SPY total-return benchmark coverage are
   enforced by contracts but not independently certified against paid data.
3. PIT fundamental vintages are implemented, but free sources do not prove full
   revision/restatement history; affected quality/value Alpha must remain blocked.
4. The transaction-cost model is conservative and internally consistent, but is
   not calibrated to this user's broker fills or live spread history.
5. Sector, size, ADV, and benchmark metadata are trusted only after upstream data
   certification; bad metadata correctly blocks or contaminates risk estimates.
6. The legacy application scheduler still performs data and research jobs. A
   production adapter that assembles certified database records into
   `DailyQuantInput` remains to be built and independently validated. Until then,
   the live database cannot automatically produce a production daily target.
7. This work does not demonstrate Alpha on real data and does not authorize real
   capital use. It provides deterministic, fail-closed infrastructure only.

Historical and fixture results do not guarantee future performance and are not
investment advice.
