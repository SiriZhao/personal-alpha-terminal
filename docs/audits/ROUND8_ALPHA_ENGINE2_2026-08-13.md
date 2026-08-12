# ROUND 8 — ALPHA ENGINE 2.0: CHAMPION / CHALLENGER

Date: 2026-08-13
Branch: `codex/round8-alpha-engine-2`
Baseline: ROUND 7 `HISTORICAL_PIT_LIMITED` (commit `7c1b618`, pushed)

## Executive Summary

ROUND 8 established a strict Champion/Challenger research framework around the
Classical Quant Core.  The Classical Quant Core remains the CHAMPION; every new
strategy is a CHALLENGER that defaults to SHADOW / RESEARCH_ONLY and never enters
production automatically.  A complete research registry, extended factor
research with redundancy diagnostics, a pre-fixed promotion gate, a Probability
challenger gate, and real shadow production are now in place.

Final state is the fully legal:

```text
CLASSICAL_CHAMPION_RETAINED
```

No model was force-swapped.  The champion remains in production because no
challenger has yet accumulated the certified forward evidence required by the
promotion gate.

## 1. Champion / Challenger

- `Champion`: Classical Quant Core (`USAdaptiveAlphaCoreV1`).
- `Challenger`: any other strategy/parameterization.  Default status is
  `RESEARCH_ONLY` or `SHADOW`; promotion requires passing the pre-fixed gate.
- No challenger enters production through shadow mode, and no challenger was
  promoted in this round.

## 2. Research Registry

`alpha_engine2/research_registry.py`:

- Append-only ledger recording EVERY experiment: strategy ID/version, hypothesis,
  factors, parameters, universe version, horizon, benchmark, cost model version,
  train/validation/OOS periods, results and **rejection reason**.
- Rejected and RESEARCH_ONLY experiments are preserved identically to promoted
  ones (no cherry-picking).
- Identical re-appends are idempotent; a conflicting payload for the same
  experiment_id is rejected.

## 3. Factor Research

`alpha_engine2/factor_research.py` provides a 12-factor research catalog with
economic rationale + PIT requirement + direction for each:

momentum_12_1, trend_slope, low_volatility, short_term_reversal,
residual_momentum, volatility_regime, liquidity, quality, profitability,
investment, value, market_breadth.

`research_factor` computes rank IC, IC-IR, positive-IC ratio, turnover, cost
adjusted value, and period stability.  Factors are research-only; they grant no
production status by themselves.

## 4. Factor Redundancy

`factor_redundancy` reports:

- Pearson correlation and rank correlation matrices
- marginal IC per factor
- incremental portfolio contribution (IC of the factor orthogonalized to the
  rest)
- redundant pairs flagged when both correlation and rank correlation exceed the
  threshold — so five differently-named momentum clones cannot silently enter a
  composite.

## 5. Promotion Gate

`alpha_engine2/promotion.py` — a pre-fixed `PromotionPolicy`:

- OOS net alpha >= 200 bps AND at least 100 bps better than the champion
- OOS Sharpe / IR >= 0.50 AND better than the champion by 0.10
- drawdown, turnover and cost must all be at least as good as the champion
- stability >= 0.60, forward consistency >= 0.50, robustness >= 0.50

A challenger that is only marginally better (e.g. +10 bps alpha) is **retained**:
`CLASSICAL_CHAMPION_RETAINED`.

## 6. Probability Challenger

`alpha_engine2/probability_challenger.py` — `evaluate_probability_challenger`
requires ALL six gates to promote:

1. calibration (Brier better than baseline)
2. discrimination (ROC-AUC >= 0.55)
3. OOS incremental value (probability net return > classical net return)
4. target-weight actual change (count > 0)
5. cost-adjusted improvement (net edge > added cost)
6. stability

Any miss keeps Probability `RESEARCH_ONLY`.

## 7. Regime

The catalog treats volatility_regime and market_breadth as
`risk_budget_only` / `exposure_only` signals.  They may adjust exposure, factor
mix or risk budget — never a coarse bull=buy / bear=sell-all switch.

## 8. Portfolio Research / Sensitivity

The framework records the full parameter grid in each research experiment
(parameters are part of the immutable lineage) so a sensitivity surface is
recoverable; no single best parameter point is implied.

## 9. Deflated Evidence

`alpha_engine2/deflated.py`:

- Deflated Sharpe Ratio (Bailey & Lopez de Prado) penalizing the number of
  trials
- parameter instability (std of Sharpe across the grid)
- sample dependence (max subperiod gap)
- OOS stability (fraction of positive OOS subperiods)
- subperiod stability

`evaluate_deflated_evidence` marks a result `inflated` when the deflated Sharpe
is not positive, parameters are unstable, or OOS subperiods are inconsistent.

## 10. Shadow Production

`alpha_engine2/shadow.py` + daily-workflow hook:

- A configured challenger (registered, non-promoted) runs inside the real
  daily-run in SHADOW mode: it records what it would recommend (shadow_id,
  run_id, decision_time, challenger, symbol, rank, expected alpha, target
  weight, recommendation) into an append-only shadow ledger.
- It **never** changes the official recommendation, target, portfolio or ledger
  (verified by test: no fills, no transactions, no positions from shadow).
- `evaluate_shadow_comparison` accumulates real forward outcomes and reports MAE
  and direction agreement; promotion requires a minimum number of outcomes.

## 11. CLI

New `round8-research` command:

- `status` — registry summary, shadow config, factor catalog
- `shadow-report` — shadow predictions + forward comparison
- `shadow-append-outcome` — record a real forward outcome
- `register-experiment` — record any experiment (incl. rejected)
- `promotion-evaluate` — run the fixed promotion gate on provided metrics

## 12. Acceptance Evidence (real terminal)

`round8-research status` showed the 12-factor catalog and an empty registry.

Direct acceptance run recorded:

```
registered REJECTED experiment -> chall-a-rejected-2024
registered RESEARCH_ONLY experiment -> chall-b-shadow-2024
promotion verdict: CHALLENGER_PROMOTED failures: ()   (fully-superior challenger)
marginal verdict: CLASSICAL_CHAMPION_RETAINED          (marginally-better challenger)
shadow comparison: predictions 12 outcomes 12 MAE 0.01 direction agreement 1.0
registry summary: {'REJECTED': 1, 'RESEARCH_ONLY': 1, 'total': 2}
```

The shadow ledger and registry live under `var/` (git-ignored).

## 13. Tests Added

`tests/unit/quant_engine/alpha_engine2/` + `tests/integration/test_round8_shadow_production.py` (21 tests):

- research registry: rejected preserved, idempotent, conflict rejected, reason
  required
- factor catalog completeness; IC/stability/cost-adjusted reporting; redundancy
  flags duplicate momentum, no false positive on uncorrelated factor
- promotion: champion retained for marginal and for worse drawdown/turnover/
  cost; promoted only when all gates pass; policy bounds
- probability challenger: promoted only on all six gates; RESEARCH_ONLY on any
  miss (e.g. no target-weight change)
- shadow ledger: append-only, immutable, unknown outcome rejected, minimum
  outcomes gate, forward direction agreement
- deflated evidence: many-trials penalty, inflation detection, no inflation for
  stable single experiment
- shadow hook in real daily run: challenger predictions recorded, production
  output untouched

## 14. Quality Gates

| Gate | Result |
|---|---:|
| Full pytest | **851 passed** |
| Ruff | PASS |
| Strict mypy (397 source files) | PASS |
| Secret scan | PASS |
| Quant-critical regression | 31 passed |
| Performance smoke | 2 passed |

## 15. Final State

```text
CLASSICAL_CHAMPION_RETAINED
```

- Champion: Classical Quant Core (production).
- Challengers: SHADOW / RESEARCH_ONLY; none promoted.
- Probability: RESEARCH_ONLY (no target-weight incremental value).
- Auto execution: disabled; forward shadow evidence must accumulate before any
  promotion is reconsidered.

## Final Verdict

**CLASSICAL_CHAMPION_RETAINED**

ROUND 8 delivered the full Champion/Challenger framework — registry, factor
research, redundancy diagnostics, fixed promotion gate, Probability challenger
gate, shadow production, and deflated evidence — without forcing a model swap.
