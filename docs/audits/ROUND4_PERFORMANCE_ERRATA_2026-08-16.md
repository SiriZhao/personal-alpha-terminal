# ROUND4 Performance Errata

Date: 2026-08-16

Status: `CONFIRMED_AND_SUPERSEDED_BY_ROUND33`

## 1. Confirmed issues

1. **Target-weight scaling bug**: `round4_research._target_weights` used
   `selected_count` twice when scaling capacity, and used the pre-filter
   selected count for capacity even when negative-alpha rows were removed.
   For a 1,959-symbol universe with 20% top fraction and 0.12 maximum weight,
   this collapsed gross exposure to roughly 1-2% instead of the intended 90%.
2. **Sharpe annualization bug**: `_sharpe` annualized sparse 21-session
   rebalance-point returns with `sqrt(252)` instead of `sqrt(252/21)`.
3. **Silent zero-cost fallback**: `_simulate_weights` caught `ValueError`
   from the cost model and assigned `cost = 0.0`. That is a performance bias.
4. **Execution convention mismatch**: ROUND4 labeled returns from
   `close[t+1]` to `close[t+horizon]`, while production executes at the next
   tradable session open.

## 2. Consequences

- The old ROUND4 reported net return `+0.017%` must not be used as corrected
  performance evidence.
- The old ROUND4 Sharpe `10.70` is not a valid annualized Sharpe for the
  research convention used at the time.
- ROUND4 probability conclusions that relied only on portfolio return should
  be re-evaluated on corrected execution, allocation, and cost. ROUND33 did
  this and found Probability still adds no after-cost incremental value.

## 3. Provenance

- Original artifact remains immutable:
  `docs/audits/QUANT_RESEARCH_CLOSURE_2026-08-12.md`.
- Corrected evidence: `reports/validation-artifacts/round33_*` artifacts.
- Corrected ROUND33 report: `docs/audits/ROUND33_QUANT_PERFORMANCE_CLOSURE_2026-08-16.md`.

## 4. Final statement

`ROUND4_PERFORMANCE_VALID = FALSE_FOR_PERFORMANCE_CLAIMS`

`ROUND33_CORRECTED_EVIDENCE_SUPERSEDES_ROUND4_PERFORMANCE_INTERPRETATION = YES`
