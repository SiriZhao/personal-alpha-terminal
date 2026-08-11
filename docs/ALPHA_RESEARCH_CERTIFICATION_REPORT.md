# Alpha Research & Strategy Certification Report

Date: 2026-08-11

Strategy: `USAdaptiveAlphaCoreV1:1.0.0`

Parameter hash: `427671e52a5391d97cd01fd855aec3bbafa7c762c072aeee253406fa993416b6`

Final classification: **NOT_CERTIFIABLE**

## 1. Data used

The run performed a read-only audit of `var/personal_alpha.db` at cutoff
`2026-08-11T09:58:57.456915+00:00`: 9,055 raw price rows, 18 securities,
2 current universe snapshots / 36 membership rows, 3 corporate actions,
162 PIT-total-return version rows, 0 historical identifier rows, 0 recorded
delisted securities, and 0 model approvals.

This is `LIVE_DAILY_DATA`, not a row-level `RESEARCH_CERTIFIED_DATA` package.
The manifest deliberately has no research `dataset_version` or `content_hash`;
an inventory hash is not misrepresented as a complete dataset hash.

- Inventory hash: `a355b3d43c4581e21fdca74e106b03e9e015046239c36ae203ceeba745263414`
- Manifest hash: `7b56c9853b9fe0a279242c01b8cbc5055f00832b65bb209cc5b2db595ddc142e`
- Latest current-universe version: `298ff9f33b6dd72cd63ae631d6d6ca3b96964ed551f7b20746822be2e567756e`

## 2. PIT and survivorship

Current daily observations pass live cutoff checks. Historical research does not
meet certification requirements: membership entry/exit history, delistings,
ticker/identifier vintages, complete PIT corporate actions, and total-return
vintages are incomplete. The two configured snapshots were not backfilled.

State: `NOT_CERTIFIABLE`. Manifest blockers:

- `HISTORICAL_MEMBERSHIP_INCOMPLETE`
- `CURRENT_CONSTITUENT_HISTORY_NOT_ALLOWED`
- `DELISTING_HISTORY_INCOMPLETE`
- `SECURITY_IDENTIFIER_HISTORY_INCOMPLETE`
- `CORPORATE_ACTION_PIT_HISTORY_INCOMPLETE`
- `PIT_TOTAL_RETURN_HISTORY_INCOMPLETE`
- `EXCHANGE_CALENDAR_INCOMPLETE`

## 3. Universe

The local universe contains 17 tradable stocks/ETFs plus `^VIX`. It is suitable
for today's configured analysis only, not historical membership evidence. A new
provider-neutral adapter/manifest contract supports future licensed or supplied
research datasets without coupling the strategy to a provider.

## 4. Factor definitions and audit

| Factor | Definition | Direction | Status |
|---|---|---|---|
| Momentum 12-1 | `close[t-21] / close[t-252] - 1` | Higher | Enabled, diagnostic |
| Trend | Annualized log-price OLS slope over 126 sessions | Higher | Enabled, diagnostic |
| Low volatility | Annualized 63-session return volatility | Lower | Enabled, diagnostic |
| Quality | Filing-vintage PIT quality composite | Higher | Disabled; no PIT fundamentals |

Features enforce `available_at <= cutoff`, positive prices, chronological
deduplication, and 252/126/63-session minimum histories. Cross-sectional processing
uses 1%/99% winsorization and robust MAD z-scores. Certification is blocked because
ETF and individual-equity diagnostics share a heterogeneous cross-section,
sector/size metadata is not research-certified, and expected-alpha coefficients
are engineering defaults rather than OOS estimates. `trend_consistency` is computed
but not used in the composite.

## 5. IC / Rank IC conclusion

Pearson IC, Rank IC, IC dispersion/ICIR, quantile monotonicity, top-bottom spread,
decay, turnover, factor correlation, and year/regime stability were **not reported
as numeric evidence**. Computing them from current constituents and retrospectively
adjusted history would introduce survivorship and possible future-action leakage.
The existing evaluator supports these metrics once a certified panel is imported;
their present status is `NOT_RUN_UPSTREAM_DATA`, not zero or failed alpha.

## 6. Walk-forward

The deterministic splitter enforces disjoint TRAIN, VALIDATION, embargo, and OOS
windows over a verified session calendar. The policy remains at least 4 folds.
No fold was created because upstream research data is not certifiable.

## 7. Locked OOS

The minimum remains 252 sessions. No locked OOS window was opened, moved, inspected,
or used for tuning. The engineering-default candidate remains `DIAGNOSTIC_ONLY`:
`candidate-e3d18bae7da45dbdc6c5411d18edbac4b1aee7fb693cb303f633d6573521350b`.

## 8. Benchmark

SPY/QQQ comparison was not run because benchmarks must share the strategy's
certified research PIT calendar and corporate-action convention. Daily benchmark
availability was not substituted for historical certification.

## 9. Gross versus net

Gross return, net return, CAGR, Sharpe, Sortino, excess return, alpha, tracking
error, and information ratio are `NOT_AVAILABLE`; no zeroes or synthetic PnL were
inserted.

## 10. Transaction costs

`us-daily-cost-v1` remains commission 0.5 bps, spread 4.0 bps, slippage 3.0 bps,
and impact coefficient 10.0 bps. The production backtest solver deducts costs from
cash before net PnL. A direct regression requires the same target with non-zero
costs to have positive booked costs, lower net return, and gross return above net.
No performance claim is made because a research backtest was not authorized.

## 11. Turnover

Strategy turnover and high-turnover cost drag are `NOT_AVAILABLE`. The annual
turnover limit remains 4.0 and was not relaxed.

## 12. Volatility and drawdown

Annualized volatility, maximum drawdown/duration, concentration, and stress results
are `NOT_AVAILABLE`. Limits remain max drawdown 25% and max position weight 15%.

## 13. Stability

No IC, year, regime, parameter-neighborhood, or execution-delay stability score was
claimed. The minimum stability score remains 0.60.

## 14. Certification gates

The run retained chronological splits; >=252 locked OOS sessions; >=4 folds; PIT,
survivorship and corporate actions; same-PIT SPY/QQQ; after-cost Sharpe/benchmark
alpha; turnover, drawdown, concentration, and stability. Failed or uncertifiable
evidence cannot write an approval artifact. Approval matching is exact on strategy
version, parameter hash, research data version/hash, and manifest hash.

Certification evidence ID:
`strategy-cert-35756af0ba72181f56f05d36c0333b6e6ce8660d746ee3c04707cc160a1f5718`.

## 15. Final conclusion

**NOT_CERTIFIABLE** — not `REJECTED` and not `PRODUCTION_APPROVED`. Alpha quality
cannot be judged before trustworthy historical membership, delisting,
corporate-action, and total-return evidence exists. `USAdaptiveAlphaCoreV1` remains
`DIAGNOSTIC_ONLY`; the formal approval registry remains empty.

Repeated real E2E runs produced run ID `alpha-research-827ee242063651a5` and result
hash `827ee242063651a5d64445e77110d49bd3085a51ef5a69fd05bd157afc720506`.

## 16. Highest-value next step

1. Import an auditable historical US universe with entry/exit, delistings, symbol
   changes, and permanent identifiers.
2. Import raw OHLCV plus PIT corporate-action/total-return vintages and hash the
   complete row dataset; validate ETFs and equities in separate cross-sections.
3. Freeze one 252+ session OOS window before factor/parameter work, run limited
   TRAIN+VALIDATION research, then open locked OOS exactly once. Only then can the
   framework decide between `REJECTED` and `PRODUCTION_APPROVED`.

Runtime evidence is ignored by Git under
`reports/research-runs/alpha-research-827ee242063651a5/`.

## Verification

- Ruff: passed (`src`, `scripts`, `tests`).
- Strict mypy: passed for 355 source files.
- Pytest: **595 passed** in 74.83 seconds.
- No tests were skipped, xfailed, removed, or weakened to create this result.
