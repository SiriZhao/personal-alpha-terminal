# ROUND 6 — LIVE PORTFOLIO LIFECYCLE & REBALANCE CLOSURE

Date: 2026-08-13
Branch: `codex/round6-live-portfolio-lifecycle`
Baseline: ROUND 5 `BROAD_UNIVERSE_PRODUCTION_READY` (commit `672c657`, pushed)

## Executive Summary

ROUND 6 upgraded the terminal from "can produce stock recommendations" to
"can maintain a real portfolio long-term".  The strict lifecycle contract is now
explicit and enforced end-to-end:

```text
Recommendation -> User Decision -> Order Intent -> Broker Fill -> Position
```

User acceptance never equals a broker fill.  Only an actual fill recorded
against a validated recommendation mutates the real ledger.  The daily run now
reports real NAV, cash, unrealized/realized P&L, daily attribution, corporate
action reconciliation state, and rebalance deltas computed from actual current
holdings plus cash.

Completion status:

```text
LIVE PORTFOLIO LIFECYCLE: PASS
REBALANCE: PASS
PARTIAL FILLS: PASS
CASH ACCOUNTING: PASS
PnL: PASS
IDEMPOTENCY: PASS
AUTO EXECUTION: DISABLED
```

## 1. Lifecycle Semantics

New module `src/personal_alpha_terminal/portfolio/lifecycle.py` encodes:

- `LifecycleStage`: RECOMMENDATION / USER_DECISION / ORDER_INTENT / BROKER_FILL /
  PORTFOLIO_POSITION.
- `semantic_action`: a full SELL of an existing position is presented as **EXIT**;
  absence of a recommendation is **NO_ACTION**; BUY / ADD / REDUCE / HOLD pass
  through.
- `PortfolioLifecycleService`: session-backed ledger analysis (PnL, NAV,
  attribution, corporate-action reconciliation).

The terminal decision list now shows EXIT instead of a raw SELL of a full
position, and HOLD/NO_ACTION when no trade is warranted.

## 2. Full Operation Semantics

The existing portfolio optimizer already worked from real current holdings +
cash + current prices + target weights and produced deltas.  ROUND 6 verifies and
hardens this through acceptance tests:

- Empty portfolio (100% cash) -> BUY/ADD recommendations.
- Existing position -> ADD/REDUCE/HOLD based on target vs current.
- Full exit -> EXIT.
- No recommendation -> NO_ACTION.
- The optimizer never assumes the portfolio starts from 100% cash each day.

## 3. Fill Reconciliation

`ManualExecutionOrderService.record_fill` now validates:

- Recommendation provenance (must exist and be accepted).
- No impossible quantity (cumulative fills cannot exceed the approved quantity).
- No negative cash (buy fills are rejected when cash is insufficient).
- Duplicate fill (same `fill_id` with a different payload is rejected; identical
  replay is idempotent).
- Partial fills (fill ratio < 100% leaves the order PARTIAL; the next daily run
  sees the actual filled quantity).
- Multiple fills per order (each with its own `fill_id` and ledger transaction).

Only a broker fill changes the real ledger.

## 4. Stale / Expired Recommendation Gate

New `evaluate_fill_gate` runs before any fill touches the ledger:

- A fill after `expires_at` is blocked (`BLOCKED_EXPIRED`) unless the user
  supplies an explicit `--override-provenance` (expiry is never silently ignored).
- A fill from a run that is no longer the latest approved run is stale
  (`BLOCKED_STALE`) and requires an explicit override provenance.
- Overrides are recorded as `ALLOWED_WITH_OVERRIDE` with the provenance string
  preserved for audit.

Wired through `ManualFillSubmission.override_provenance` ->
`DecisionService.mark_executed` -> `ApplicationService.mark_candidate_executed` ->
CLI `mark-executed --override-provenance`.

## 5. Cash Accounting

The existing immutable ledger applies:

```text
Cash before
+ Sell proceeds (qty * price - fee)
- Buy settlement (qty * price + fee)
- Fees
= Cash after
```

Recommendation amounts are never used to change cash; only recorded fills do.
Cash accounting is verified in tests (buy reduces cash by qty*price+fee; sell
adds proceeds).

## 6. PnL and NAV

`PortfolioLifecycleService` computes per-position and portfolio-level:

- cost basis (average cost x quantity)
- market value
- unrealized P&L
- realized P&L (average-cost allocation over the immutable sell ledger)
- total NAV (cash + market value)
- position weights

Real daily-run evidence (`daily-90f061bb...`):

```text
NAV $100,000.00   Cash $100,000.00   Invested 0.00%   Cash weight 100.00%
Unrealized P&L --   Realized P&L --   Cost basis --
Beginning NAV --   Ending NAV $100,000.00
Market P&L $0.00   Trading P&L $0.00   Fees $0.00
```

(The real portfolio currently holds only cash; the initial $100,000 deposit is
the genuine `portfolio_initialization` ledger entry.)

## 7. Daily Attribution

`daily_attribution` decomposes the day:

- beginning NAV / ending NAV
- external flow (deposits/withdrawals)
- fees
- realized P&L change -> trading P&L
- total P&L - trading P&L -> market P&L
- portfolio return, benchmark return, active return

Benchmark return is supplied by the daily workflow's benchmark evidence.

## 8. Corporate Actions

`corporate_action_reconciliation` never auto-applies a corporate action.  If a
split, reverse split, cash dividend, stock dividend, symbol change, merger or
delisting affects a held security and no matching ledger transaction was
recorded on/after the effective date, the position is marked
**RECONCILIATION_REQUIRED** and its symbol is removed from today's
recommendation list (fail-closed).  The terminal displays the flagged actions.

## 9. Rebalance Engine + No-Trade Region

Rebalance deltas are computed as `target weight - current weight` over real
holdings.  The existing no-trade band and minimums are now **config-driven** and
part of the portfolio constraint hash (and therefore the strategy identity):

```yaml
no_trade_band: 0.005
minimum_rebalance_weight: 0.01
minimum_trade_value: 100.0
```

Changing these thresholds invalidates existing operational approvals (identity
mismatch), matching the ROUND 5 policy rule.

## 10. Recommendation Expiry

Recommendations already bind run_id, trade date, earliest execution and expiry.
ROUND 6 adds the enforcement gate (Section 4): expired recommendations cannot
record a new fill without an explicit manual-override provenance.

## 11. Idempotency

- `QuantDecisionRun` unique `(portfolio_id, as_of_time, input_fingerprint)`
  prevents duplicate runs for the same decision inputs.
- Duplicate `fill_id` replays are idempotent; conflicting payloads are rejected.
- Immutable `PortfolioTransaction.external_id` prevents double booking.
- Verified by `test_idempotent_repeat_daily_run_does_not_duplicate_actions`.

## 12. Tests Added

`tests/unit/portfolio/test_round6_lifecycle.py` (8 tests):
- semantic actions (EXIT / NO_ACTION / BUY / ADD / REDUCE / HOLD)
- fill gate (valid, expired, stale, override)
- expired fill blocked in record_fill
- PnL (cost basis, unrealized, realized, NAV)
- daily attribution decomposition
- corporate-action reconciliation flag

`tests/integration/test_round6_live_portfolio_lifecycle.py` (9 tests):
- Scenario A: 100% cash -> BUY without fill
- Scenario B: partial fill (40 of 100)
- Scenario C: second-day run reflects actual 40-share fill
- Scenario D: full sell -> EXIT / position removed
- Scenario E: user reject -> ledger unchanged
- duplicate fill rejected
- stale recommendation requires override
- idempotent repeat daily run
- lifecycle snapshot reports PnL and NAV
- no broker API / no auto execution

## 13. Quality Gates

| Gate | Result |
|---|---:|
| Full pytest | **812 passed** |
| Ruff | PASS |
| Strict mypy (382 source files) | PASS |
| Secret scan | PASS |
| Quant-critical regression | 31 passed |
| Performance smoke | 2 passed |

## 14. Real Daily Run

Run ID `daily-90f061bb08c344a283fe5635cf6f3e23`:
- Classification: `VALID_ANALYSIS_NON_ACTIONABLE`
- Lifecycle snapshot: `status=OK`
- PnL/attribution/reconciliation persisted in `run_certificate.json`
- `automatic_execution: false`, `manual_broker: Charles Schwab`
- Ledger unchanged (no fills, no recommendations executed)

## 15. Remaining Limitations

1. The real portfolio currently holds cash only; position-level P&L is proven by
   the isolated acceptance tests and will accrue as fills are recorded.
2. Corporate actions are never auto-applied; every affected position requires
   user reconciliation.
3. Probability remains `RESEARCH_ONLY`.
4. Live capital remains manual; recommendations require user review and manual
   Charles Schwab execution.

## Final Verdict

**LIVE PORTFOLIO LIFECYCLE: PASS**

All ROUND 6 completion criteria are met and verified by 17 new tests plus a real
daily run.  Auto execution remains disabled; only user-recorded broker fills
mutate the real ledger.
