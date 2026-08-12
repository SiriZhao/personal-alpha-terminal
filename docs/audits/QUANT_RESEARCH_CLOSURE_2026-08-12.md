# QUANT RESEARCH CLOSURE 2026-08-12

## Executive Summary

ROUND 4 moved the terminal from a fixed 9-stock cross-section to a real
current-directory price-based factor universe. As of the acceptance daily run,
the broad universe funnel was:

- US listed securities: 8,833
- Listed equities: 7,475
- Security-type eligible: 4,957
- Strict certified PIT total-return factor eligible: 9
- Price-based ranking data eligible: 3,139
- Price-based ranking liquidity eligible: 1,959
- Price-based ranking factor eligible: 1,959

The strict production alpha universe remains 9 because free Yahoo OHLCV cannot
prove PIT corporate-action and total-return vintages for the broad universe.
The price-based universe is explicitly labeled `PRICE_BASED_RANKING` and
`SURVIVORSHIP_LIMITED`; it is not promoted to production certification.

Probability calibration now produces a real temporal-split artifact, but its
OOS discrimination is not materially better than chance and it changed no
target weights in the real OOS comparison. It therefore remains research-only.

Final verdict: `PRODUCTION_READY_DEGRADED_RESEARCH`.

## Baseline

- Branch: `codex/quant-core-closure-part1`
- Prior full pytest baseline: 762 passed
- This round full pytest: 775 passed
- Ruff: PASS
- Strict mypy: PASS (378 source files)
- Secret scan: PASS
- Daily run: `daily-e018ab8194814817b882d6074033348b`
- Classification: `VALID_ANALYSIS_NON_ACTIONABLE`
- Auto execution: disabled
- Ledger: unchanged

## Universe Expansion

Real `broad-universe` backfill downloaded 2024-08-01 through 2026-08-12 in
per-chunk committed batches. The funnel includes both the strict certified path
and the honest price-based diagnostic path.

| Layer | Eligible | Notes |
|---|---:|---|
| US listed securities | 8,833 | Nasdaq Trader current directory |
| Listed equities | 7,475 | non-test, non-ETF rows |
| Security-type eligible | 4,957 | common-stock/exchange/financial-status filters |
| Strict data eligible | 9 | certified PIT total-return versions |
| Strict liquidity eligible | 9 | same strict universe |
| Strict factor eligible | 9 | production-safe only |
| Price-based data eligible | 3,139 | raw PIT OHLCV availability |
| Price-based liquidity eligible | 1,959 | ADV/median dollar-volume thresholds |
| Price-based factor eligible | 1,959 | liquidity + 252-session feature coverage |

The expansion root cause is now explicit: 4,957 common stocks were registered,
but the previous daily provider only downloaded the 18 bootstrap symbols. The
new batch provider maps Yahoo share-class tickers, downloads 100 symbols per
chunk, isolates failed symbols, commits each chunk, and exposes quarantine.

## Data Coverage

- Registered broad common stocks: 4,957
- Stocks with real downloaded price history: 4,955
- Price rows: 2,315,885
- Latest completed session: 2026-08-11
- Quarantined symbols: reported by `broad-universe status`

Historical membership remains unavailable from Nasdaq Trader and Yahoo. The
report therefore records `SURVIVORSHIP_LIMITED`; historical OOS is not claimed
to be survivorship-safe.

## Factor Validation

`round4-research` uses the same PIT raw close cutoffs as the production feature
layer and computes momentum, trend slope and low volatility, then applies
within-day cross-sectional winsorization, robust z-scoring, and explicit
degraded neutralization because sector/size metadata is not certified.

Latest diagnostics:

| Factor | Rank IC | Positive IC ratio | Top-bottom spread |
|---|---:|---:|---:|
| momentum_12_1 normalized | 0.067 | positive | -0.018 |
| trend_slope normalized | 0.062 | positive | -0.021 |
| volatility normalized | 0.101 | positive | -0.034 |
| composite | 0.087 | positive | -0.026 |

The positive Rank IC is not sufficient for production certification because the
historical universe is current-survivor-only and the expected-alpha coefficients
remain engineering defaults.

## Probability Calibration

A real temporal train/calibration/OOS split was trained on the price-based
factor panel. Latest evidence:

| Metric | Value |
|---|---:|
| Training samples | 8,485 |
| Calibration samples | 25,967 |
| OOS samples | 17,789 |
| OOS base rate | 0.4149 |
| Brier | 0.2444 |
| Log loss | 0.6818 |
| ECE | 0.0532 |
| ROC-AUC | 0.5200 |

The artifact is bound to strategy, feature schema, factor identity, universe
identity, benchmark, horizon, transaction-cost assumption, periods, and a
content hash. It is saved under `var/round4-research/latest.json`.

## Probability Incremental Value

The A/B test applies the calibrated probabilities through a capped multiplier:
`adjusted_alpha = base_alpha * (1 + cap * (2*p - 1))`.

- Classical-only OOS net return: +0.017%
- Classical + Probability OOS net return: +0.017%
- Alpha rows changed by probability: 4,413
- Target-weight rows changed by probability: 0

Conclusion: `NO` in real OOS evidence. The probability layer is retained as
`RESEARCH_ONLY` and the classical champion remains unchanged. The integration
mechanism is covered by unit tests showing that high-contrast calibrated
probabilities can change target weights.

## Walk-forward

- Train period: 2024-08-30 to 2025-09-04
- Calibration period: 2025-10-03 to 2026-03-06
- OOS period: 2026-04-07 to 2026-08-06
- Rebalance dates: 24
- Factor rows: 52,241

The split is chronological and disjoint. It is not claimed to satisfy a 252
locked-OOS production approval because broad historical membership is not
certified.

## OOS

OOS Rank IC and quantile evidence are positive but small. OOS net alpha after
transaction cost is approximately +0.017% over the OOS rebalance period in the
simple top-quintile research portfolio. This is not production-approved.

## Benchmark Comparison

Using the same PIT daily-close convention:

| Benchmark | Period return | Annualized vol | Max drawdown |
|---|---:|---:|---:|
| SPY | +48.57% | 16.74% | -19.00% |
| QQQ | +35.75% (daily-run window) | 23.15% | -22.88% |

## Transaction Cost

Configured model: commission 0.5 bps, half-spread 2 bps, slippage 3 bps,
impact coefficient 10 bps, max ADV participation 2%. Research A/B reports net
after this model and shows gross/net separation in the report artifact.

## Risk Attribution

Strict production risk attribution is still blocked at SIGNAL because no
immutable strategy approval exists. The price-based research portfolio reports
target construction, turnover, and cost in `var/round4-research/latest.json`.
`size_neutralization:degraded` remains because market-cap metadata is absent;
the production size gate was not lowered.

## Leakage Tests

- Future-row price poison does not change factor raw/normalized values.
- Future cross-sectional security does not change historical universe or ranks.
- PIT/available-time filtering is enforced by existing production data gates.

## Survivorship Status

`SURVIVORSHIP_LIMITED`

Current-directory rows are not backfilled into historical membership. No
delisting history, identifier history, PIT corporate-action vintage, or PIT
total-return vintage is fabricated for the broad universe.

## Forward Validation Status

An immutable `ForwardPrediction -> ForwardOutcome` ledger was added under
`src/personal_alpha_terminal/quant_engine/forward_track.py`. It permits future
outcomes to be appended but never mutates the original recommendation.

## Production Daily Run

`python main.py --no-refresh daily` completed with:

- DATA: PASS
- PIT: PASS
- FEATURE: PASS
- FACTOR: PASS (9 strict, 1,959 price-based at run time)
- SIGNAL: BLOCKED because strategy has no locked OOS/survivorship approval
- PROBABILITY: PASS_DEGRADED / `PROBABILITY_ARTIFACT_MISSING`
- Ledger: unchanged

## Test Results

- Full pytest: 775 passed
- Ruff: PASS
- Strict mypy: PASS
- Secret scan: PASS

## Remaining Limitations

1. Free current-directory data cannot certify broad historical membership.
2. Broad PIT corporate-action/total-return vintages are unavailable.
3. Strict production alpha universe remains 9.
4. Probability OOS has no target-weight incremental value.
5. Market-cap/sector metadata for size neutralization is unavailable.

## Final Verdict

`PRODUCTION_READY_DEGRADED_RESEARCH`

The real broad price-based universe, chunked data pipeline, factor diagnostics,
probability calibration artifact, OOS validation, leakage tests, and immutable
forward ledger are now in place. They are not promoted to full production
certification because the statistical evidence and historical data do not
support it.
