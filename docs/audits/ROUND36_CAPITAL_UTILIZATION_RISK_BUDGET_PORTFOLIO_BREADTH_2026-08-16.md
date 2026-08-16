# ROUND36 Capital Utilization / Risk Budget / Portfolio Breadth

Date: 2026-08-16

Baseline: ROUND35 commit `05343b4`

Verdict:

`NO_FIXED_TOP_N=PASS`

`CAPITAL_UTILIZATION_RESEARCH=PASS`

`PORTFOLIO_BREADTH_RESEARCH=PASS_WITH_FIXTURE_SUPPLEMENT`

`RISK_BUDGET_RESEARCH=DATA_INSUFFICIENT_FOR_CERTAIN_GRID`

`PRODUCTION_POLICY_UNCHANGED=PASS`

`READY_FOR_ROUND37=YES`

## Current production

The real current run has:

- optimizer input: `1171`
- final target/action count: `10`
- gross: `27.23%`
- cash: `72.77%`
- expected vol: `7.60%`
- pre-optimizer Top-N: `null`
- fixed holdings cap: `null`

## Research boundary

The breadth/gross frontier artifacts reuse the existing deterministic
ROUND31 fixture and are explicitly labeled `FIXTURE_SUPPLEMENTARY`. They are
not certified corrected OOS evidence. The risk-budget grid is recorded as
insufficient because no survivorship-safe corrected OOS grid was established.

## Policy

`CURRENT_POLICY_RETAINED`

No production policy change is supported by evidence. Any future change
requires human approval.

## Artifacts

`reports/validation-artifacts/round36_*.json`
