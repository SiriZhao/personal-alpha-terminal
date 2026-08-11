# Paper Forward Validation Report

Date: 2026-08-11

## Classification

**PAPER READY / PRODUCTION NON_ACTIONABLE.** `paper-100k` is an isolated USD 100,000 cash-only simulation
ledger. `USAdaptiveAlphaCoreV1` remains `DIAGNOSTIC_ONLY`; the production approval registry remains empty and
production actions remain zero.

## Frozen experiment

- Experiment: `paper-usadaptive-v1-20260811`
- Strategy: `USAdaptiveAlphaCoreV1:1.0.0`
- Parameter hash: `427671e52a5391d97cd01fd855aec3bbafa7c762c072aeee253406fa993416b6`
- Factors: 12-1 momentum, 126-session trend, 63-session low volatility; quality weight remains zero.
- Constraints: long-only; 12% maximum position; 90% maximum gross exposure; 10% minimum cash; 30% maximum
  turnover; sector, HHI, minimum-trade, and ADV controls remain active.
- Cost model: `us-daily-cost-v1`; commission 0.5 bps, spread 4 bps (half per side), slippage 3 bps, and
  square-root market impact coefficient 10 bps.

Every experiment, signal, recommendation, user decision, fill, observation, and daily snapshot is
content-hashed and immutable. A strategy change requires a new experiment ID; old experiments are retained.

## Time and execution convention

A decision after session T close may use only data available at or before its cutoff. The earliest eligible
fill is the next valid XNYS session raw open. The fill applies adverse half-spread, slippage, and impact;
commission and regulatory fees adjust cash separately. Same-session, pre-decision, wrong-session, unavailable,
best-price, missing-provenance, and over-ADV fills fail closed. The execution bar binds its provider/source and
content hash. A target is not a holding, and `ACCEPT` is not a fill.

## Ledger and performance

Paper artifacts live under ignored `var/paper-trading/<portfolio_id>/`; the real SQL portfolio tables are never
accessed by the paper service. Daily marks require same-date prices for every holding plus SPY and QQQ. Both
benchmarks start at USD 100,000. NAV is cash plus marked position value. Costs, PnL, drawdown, turnover, and
trade count are retained. Annualized statistics remain `INSUFFICIENT_SAMPLE` for short samples.

## E2E evidence

- A: initialized `paper-100k` with NAV/cash exactly USD 100,000 and zero positions.
- B: a controlled fixture completed candidate -> paper signal -> constrained action -> explicit accept ->
  next-session cost-adjusted fill -> next-day mark; cash plus position market value equaled NAV.
- C: normal daily production remained non-actionable with `STRATEGY_NOT_PRODUCTION_APPROVED`; the separate paper
  portfolio loaded as ready. The live observation produced zero actions because validated paper risk/execution
  inputs were unavailable; no BUY was manufactured.

## Safety conclusion

Forward paper evidence does not repair missing survivorship-safe historical membership, delisting,
security-identity, PIT corporate-action, total-return, locked-OOS, or walk-forward evidence. It cannot register
a `PRODUCTION_APPROVED` artifact and must not be used as a real trading instruction.

## Verification

- Ruff: passed for `src` and `tests`.
- Strict mypy: passed for 359 source files.
- Pytest: 628 passed in 57.36 seconds; no skips/xfails were added.
- Runtime paper ledger is Git-ignored; tracked-source secret scan passed.

The branch and commit are recorded in the final handoff after push.
