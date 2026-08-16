# ROUND33 Quant Performance Closure

Date: 2026-08-16

Verdict: `ROUND33_ALPHA_NOT_ESTABLISHED`

Ready for ROUND34: `YES_WITH_FORWARD_VALIDATION`

## Baseline

- BASELINE_BRANCH: `codex/round27-31`
- BASELINE_SHA: `334d6f3fb86eb52d554d40b7936a123d722c716e`
- ROUND32_SHA: `334d6f3fb86eb52d554d40b7936a123d722c716e`
- WORKTREE_INITIAL_STATUS: modified `round32_audit.py`, `run_bundle.py`,
  `terminal/cli.py` (preserved; not committed or reverted)
- ROUND32 bundle replay: `REPLAY_PASS`
- Pre-optimizer Top-N: `null`
- Fixed holdings cap: `null`
- Optimizer input count: `1171`
- Formal action count: `10` (optimizer-decided, not a fixed Top-10)

## Corrected evidence boundary

`RESEARCH_ONLY_SURVIVORSHIP_LIMITED`

`CORPORATE_ACTION_LIMITED`

`PRICE_BASED_RANKING`

The corrected historical evidence uses the broad current-directory price-based
universe. It does not claim survivorship safety, PIT corporate-action vintage,
or production certification.

## Corrected OOS

Window: decision dates `2026-05-06` to `2026-07-08`; backtest daily NAV from
`2026-04-06` to `2026-08-06`.

Independent decision dates: 3.

OOS rows: 13,136.

Daily observations: 85.

All strategies use `NEXT_SESSION_OPEN_TO_HORIZON_CLOSE`, explicit daily
frequency, and the same cost model.

### Champion classical

- Total return: `-2.193%`
- Annualized return: `-6.363%` (SHORT_SAMPLE_ANNUALIZATION)
- Annualized vol: `20.108%`
- Sharpe: `-0.227`
- Sortino: `-0.318`
- Max drawdown: `-10.519%`
- Alpha vs SPY: `-50.69%` annualized
- Information ratio: `-3.455`
- Turnover: `1.719`
- Transaction cost: `$965.45`
- Average gross: `64.48%`
- Average cash: `35.52%`

### AlphaCalibrationV1 regularized IC-weighted challenger

- Total return: `+1.399%`
- Annualized return: `+4.205%` (SHORT_SAMPLE_ANNUALIZATION)
- Annualized vol: `10.849%`
- Sharpe: `+0.433`
- Sortino: `+0.663`
- Max drawdown: `-4.272%`
- Alpha vs SPY: `-18.45%` annualized
- Information ratio: `-3.843`
- Turnover: `1.690`
- Transaction cost: `$945.98`
- Average gross: `65.01%`

The challenger is numerically less bad than the Champion but remains negative
alpha and is not promoted. `CLASSICAL_CHAMPION_RETAINED`.

### Benchmarks, same window

| Metric | SPY | QQQ |
|---|---:|---:|
| Total return | `+16.638%` | `+21.436%` |
| Annualized return | `+57.818%` | `+77.854%` |
| Volatility | `13.743%` | `24.366%` |
| Sharpe | `3.391` | `2.486` |
| Max drawdown | `-4.495%` | `-11.315%` |

These annualized values are short-sample and must be read with
`SHORT_SAMPLE_ANNUALIZATION`.

### Uncertainty

- Annualized alpha point estimate: `-0.514`
- Alpha 95% CI: `[-0.938, -0.210]`
- Sharpe 95% CI: `[-0.937, 0.515]`
- Max drawdown 95% CI: `[-0.131, -0.045]`

The alpha CI does not cross zero; it is materially negative on this short
research-only sample. Verdict: `ROUND33_ALPHA_NOT_ESTABLISHED`.

## Factor evidence

| Factor | Mean Rank IC | Top-bottom spread | Net spread after cost |
|---|---:|---:|---:|
| momentum | `0.0712` | `-0.0110` | `-0.0112` |
| trend | `0.0703` | `-0.0103` | `-0.0105` |
| low volatility | `0.1008` | `-0.0238` | `-0.0239` |
| composite | `0.0933` | `-0.0156` | `-0.0158` |

Rank IC remains positive, but top-bottom spread remains negative. Date-count
coverage is only 12 decision dates, and `sufficient_independent_dates=false`
for horizon-length block inference. This is insufficient to establish factor
profitability.

## Alpha calibration

The current Champion coefficients `0.006 / 0.003 / 0.002` are not supported as
calibrated return forecasts. `AlphaCalibrationV1` challengers:

- Non-negative ridge: momentum `0.00209`, trend `0.00354`, low volatility `0.0`
- Regularized IC-weighted: `0.2152 / 0.2148 / 0.2023` on rank features

No challenger passes ROUND8 promotion. `CHALLENGER_PROMOTION_ELIGIBLE = FALSE`.

## Probability retest

- Brier: `0.2517` vs baseline `0.2477`
- Log loss: `0.6967`
- ROC AUC: `0.4969`
- ECE: `0.0616`
- Decision dates: 3
- Target-weight change count: 3
- After-cost alpha delta: `-0.0012`
- Sharpe delta: `-0.0120`
- Turnover/cost delta: positive

Probability remains `RESEARCH_ONLY`, production influence `0.0%`.

## Expected alpha semantics

ROUND32 `expected_alpha = 0.1394735` is the optimizer-weighted annualized
engineering return proxy:

`expected_excess_return * 252 / horizon`

It is not an OOS-calibrated expected annual excess return.

`calibration_status = UNCALIBRATED_ENGINEERING_RETURN_PROXY`

It may not be displayed as an expected annualized excess return.

## Answer summary

1. ROUND4 weight bug: `CONFIRMED`
2. Gross distortion: collapses 1959/20% case from ~90% to ~1-2%
3. Old `+0.017%`: `INVALID_AS_PERFORMANCE_EVIDENCE`
4. Old Sharpe: `CALCULATION_ERROR`
5-7. Corrected Champion/SPY/QQQ: see tables above
8. Classical after-cost Alpha: `-50.69%` annualized, short research sample
9. Alpha CI: negative, not crossing zero
10. Rank IC: still positive
11. Top-bottom spread: still negative
12. `0.006/0.003/0.002`: no statistical support as calibrated forecast
13. Calibrated challenger coefficients: see alpha calibration section
14. Challenger clearly superior: no; less negative on this sample but not eligible
15. ROUND8 promotion gate: `NOT_MET`
16. Probability changed target weights in corrected research: yes (3 dates)
17. Probability increased after-cost alpha: no
18. Probability production influence: `0.0%`
19. ROUND32 expected alpha meaning: annualized engineering score-to-return proxy
20. Can it be called expected annualized excess return: no
21. Production optimizer input: `1171`
22. Fixed Top-N: none
23. Formal action count: `10`
24. ROUND32 bundle replay: `REPLAY_PASS`
25. Most credible expectation: not enough mature evidence to state positive
26. Evidence to beat SPY long-run: no
27. Evidence to beat QQQ long-run: no

## Artifacts

`reports/validation-artifacts/round33_*`

## Final

`NO_PRODUCTION_POLICY_CHANGE_RECOMMENDED`

Continue forward validation and future survivorship-safe data certification.
