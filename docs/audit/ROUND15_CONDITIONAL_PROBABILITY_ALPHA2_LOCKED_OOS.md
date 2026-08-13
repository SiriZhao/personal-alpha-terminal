# ROUND 15 - Conditional Probability Alpha 2.0 Locked-OOS Research

Date: 2026-08-14

Verdict: `PROBABILITY_FALLBACK_CLASSICAL`

## Executive conclusion

ROUND15 defined and executed a real conditional-probability research protocol
for benchmark-relative outcomes at 5/10/21/42 session horizons. The current
corpus is far too small and too single-issuer to estimate credible calibrated
probabilities or to evaluate portfolio integration. The correct production
state remains `PROBABILITY_FALLBACK_CLASSICAL` with `production_weight = 0`.

No probability model was fitted on the insufficient sample, no arbitrary
probability weight was invented, no promotion candidate was generated, and no
production influence was enabled.

## Target definition

Targets:

- P(future benchmark-relative return > 0 | classical factors, market state,
  risk, validated LLM/PIT features)
- horizons: 5, 10, 21, 42 sessions

Real ROUND15 target evidence:

- horizon 5: 15 observations, calibration not computed, insufficient
- horizon 10: 15 observations, calibration not computed, insufficient
- horizon 21: 0 observations, insufficient
- horizon 42: 0 observations, insufficient

## Feature and model policy

The requested feature set includes classical alpha factors, factor ranks,
volatility, liquidity, cross-sectional context, and market regime. The current
Round15 dataset has no certified classical factor panel and no broad
cross-section. Round14 LLM features were not validated, so they were not forced
into a production model.

Candidate models were not fitted because the sample is insufficient:

- ridge logistic: not evaluated
- elastic-net logistic: not evaluated
- isotonic calibrated: not evaluated
- Platt calibrated: not evaluated
- gradient boosting: not evaluated
- simple ensemble: not evaluated

## Validation and calibration

- Purged walk-forward folds available: 1 (minimum required: 4)
- Locked OOS observations: 75 (minimum required: 252)
- Brier Score / Log Loss / ECE: withheld because calibration samples are
  insufficient
- Reliability curve: not fabricated
- Calibration by year/regime/probability bucket: not evaluated

## Counterfactual

Probability OFF vs Probability ON was not fabricated:

- probability off: `CLASSICAL_CHAMPION`
- probability on: `BLOCKED`
- changed recommendations: 0
- changed target weights: 0
- turnover delta: 0.0
- cost delta: 0.0
- net alpha contribution: none

## Portfolio cardinality research

`PORTFOLIO_CARDINALITY_RESEARCH` was defined for 5/10/15/20/30 holdings, but no
recommendation was produced because there is no certified broad portfolio
backtest on the current corpus.

- status: `NOT_EVALUATED_NO_CERTIFIED_BROAD_PORTFOLIO_BACKTEST`
- recommendation: none
- confidence: none

Current production `maximum_holdings = 10` remains unchanged.

## Promotion gate

Blockers:

- `CALIBRATION_NOT_CREDIBLE`
- `CROSS_SECTION_INSUFFICIENT`
- `LLM_FEATURES_NOT_VALIDATED`
- `LOCKED_OOS_SAMPLE_INSUFFICIENT`
- `RESEARCH_LIMITED_SURVIVORSHIP`
- `WALK_FORWARD_FOLDS_INSUFFICIENT`

No `PROBABILITY_PROMOTION_CANDIDATE` was generated. Production weight remains
`0.0`.

## Quality gates

- Full pytest: `961 passed`
- `quant_critical`: `31 passed`
- ROUND15 focused tests: `5 passed`
- Ruff: `All checks passed`
- Strict mypy: `Success: no issues found in 420 source files`
- Secret scan: `SECRET_SCAN_PASS`

## Final disposition

`PROBABILITY_FALLBACK_CLASSICAL`

No production influence, no promotion candidate, no policy renewal, and no
automatic execution were generated. ROUND16 scope is not defined in this
prompt, so no further autonomous round was started.
