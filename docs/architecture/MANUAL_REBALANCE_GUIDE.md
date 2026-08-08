# Manual Rebalance Guide

**Execution mode:** Manual review only. No broker connection and no automatic order submission.

## Required workflow

1. Update data after the US close.
2. Run validation and inspect the central `ResearchDataGate` decision.
3. Stop if the decision is `BLOCKED`; no ticket may be generated.
4. Generate base sleeve signals, conditional evidence and risk overlays.
5. Construct the constrained target portfolio.
6. Compare the target with current recorded holdings.
7. Review each ticket: identity, current/target weight, shares, cost, liquidity, earnings risk, evidence grade and invalidation condition.
8. Mark it accepted, rejected, modified or deferred and record the reason.
9. Place any order manually outside Personal Alpha Terminal.
10. Record actual price, shares, fees and timestamp.
11. Review implementation shortfall, slippage, completion ratio, target deviation and signal decay.

The application must never decide the amount of real capital to deploy. A suggested share count is a research calculation, not an order.

## Current implementation status

- Gate-enforced ticket calculation and fill-attribution mathematics: **Implemented and fixture-tested**.
- Persistent models for tickets and fills: **Implemented**.
- Complete review/fill UI and paper ledger: **Not Implemented**.
- Real-data validation: **Blocked**.
