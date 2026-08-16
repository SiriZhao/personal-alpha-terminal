# ROUND35 Production Counterfactual / Decision Attribution

Date: 2026-08-16

Baseline: ROUND34 commit `699e652`

Verdict:

`PRODUCTION_COUNTERFACTUAL=PASS`

`DECISION_ATTRIBUTION=PASS`

`FIXTURE_DEPENDENCY_REMOVED_FOR_NEW_RUNS=PASS`

`READY_FOR_ROUND36=YES`

## Frozen input

The ablation uses `daily-33c600f064504fd9a71a596e36080fe6` immutable bundle
inputs reconstructed by `reconstruct_optimizer_inputs`. No provider data is
refreshed and no fixture is used for the production explanation.

## Results

The largest single-module effect on this run is the covariance/risk model:

- covariance/risk model off: max weight delta `0.0279`, 15 symbols changed
- transaction cost off: max weight delta `0.00000446`
- turnover penalty off: max weight delta `0.00000389`
- probability on/off: `0`
- LLM influence: `0`
- market regime/other constraints had no material target effect in this frozen run

Methodology is leave-one-module-out. Contributions are not summed because
optimizer modules interact nonlinearly.

## Explicit unavailable sleeve ablation

Momentum, trend, low-volatility, and quality sleeve-level attribution cannot be
reconstructed from the ROUND32 frozen bundle because the persisted alpha blob
does not include per-factor component values. This is recorded as
`REQUIRES_PERSISTED_FACTOR_COMPONENTS_NOT_IN_ROUND32_BUNDLE`, not fabricated.

## Artifacts

`reports/validation-artifacts/round35_*.json`

## Final

`NO_PRODUCTION_POLICY_CHANGE_RECOMMENDED`
