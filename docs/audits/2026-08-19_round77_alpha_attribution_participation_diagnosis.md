# ROUND77 — Alpha Attribution & Participation Diagnosis

Date: 2026-08-19

## Verdict

**Engineering implementation: PASS.**

**Economic diagnosis: `BLOCKED_DATA_QUALITY`.** There is no certified historical
replay panel, survivorship-safe benchmark-aligned OOS package, or legal
historical execution evidence. No synthetic stress conclusion or current-survivor
sample was used as an economic conclusion.

## Delivered diagnosis contract

- Added `research.alpha_diagnosis` for certified replay artifacts only. It
  computes cumulative/annualized return, SPY/QQQ excess, Sharpe, Sortino,
  Information Ratio, drawdown, volatility, downside deviation, beta, tracking
  error, upside/downside capture, hit/winner/loser statistics, turnover, costs,
  concentration, average exposure and average cash using session annualization.
- Active-return attribution is explicit:
  `active return = selection alpha + timing/exposure alpha + cost drag + residual`.
  A result is rejected when numerical residual is outside tolerance; residual is
  never relabelled as alpha.
- Cash must reconcile exactly and is classified into `INTENTIONAL_RISK_CASH`,
  `NO_VALID_OPPORTUNITY_CASH`, `OPTIMIZER_ARTIFACT_CASH`,
  `CONSTRAINT_BINDING_CASH`, `ROUNDING_CASH` and `DATA_QUALITY_CASH`.
- Fixed-selection counterfactuals rescale the same selected names only for
  current/80%/90%/100%/risk-targeted/adaptive experiments; they cannot silently
  rerank, add or remove names.
- Regimes are deterministic and require only decision-time-available trailing
  return/drawdown/recovery inputs. Future-available regime inputs are rejected.
- Paired session block bootstrap is deterministic and returns
  `INSUFFICIENT_SAMPLE` instead of invented confidence below the configured
  sample threshold.

## Required questions — current answers

1. Normal-market underperformance real? **NOT ESTABLISHED / N/A.**
2. Bull-market underperformance real? **NOT ESTABLISHED / N/A.**
3. Stock-selection contribution? **NOT ESTABLISHED / N/A.**
4. Low-exposure/high-cash contribution? **NOT ESTABLISHED / N/A.**
5. Transaction-cost/slippage contribution? **NOT ESTABLISHED / N/A.**
6. Downside protection offset of lost upside? **NOT ESTABLISHED / N/A.**
7. Alpha Engine 3 selection improvement? **NOT ESTABLISHED / N/A.**
8. Adaptive Exposure participation improvement? **NOT ESTABLISHED / N/A.**
9. Prior synthetic conclusion contradicted by real evidence? **NOT ESTABLISHED / N/A.**
10. Exact next failure mode to optimize? **NOT ESTABLISHED / N/A.**

The shared exact reason is missing certified PIT/survivorship/benchmark/
tradability data and a sealed, executed real locked-OOS protocol. ROUND77 does
not infer a bull/normal-market failure mode from synthetic stress tests.

Machine-readable current status:
`docs/audits/2026-08-19_round77_alpha_diagnosis_status.json`.

## QA

- Final focused replay and diagnosis subset: `14 passed`.
- Broad PIT/replay/backtest/attribution/performance regressions: `136 passed`.
- Quant-critical production contract suite: `6 passed`.
- `main.py alpha-diagnosis --json`: PASS as a status command; all economic
  answers were `NOT ESTABLISHED / N/A` and status was `BLOCKED_DATA_QUALITY`.
- Ruff: PASS.
- Strict mypy (ROUND74-77 sources and CLI): PASS, 6 source files.
- Secret scan: `SECRET_SCAN_PASS`.
- Final ROUND73 real normal-terminal regression: `4.664s` to usable local
  terminal frame (under the 10-second hard ceiling); refresh was detached and
  cached output remained non-actionable.

No Alpha Engine 4 was created. Production Quant remains the champion; Alpha
Engine 3 and Adaptive Exposure remain challengers, while Probability and LLM
retain zero formal production influence.
