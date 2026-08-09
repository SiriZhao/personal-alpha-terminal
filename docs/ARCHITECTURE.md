# Current Architecture

```text
Canonical Market Data
        -> Point-in-Time Clean Data
        -> Features and Factor Observations
        -> Unified Alpha / USAdaptiveAlphaCoreV1
        -> Conditional Evidence (calibrated only with separate OOS artifact)
        -> Portfolio Construction
        -> Risk Budget, Causal Correlation and Governed Stress
        -> Final Decision and Trade Difference
        -> Manual Execution Plan
        -> Immutable DailyQuantResult Snapshot
        -> Rich Terminal Renderer
```

`ApplicationService.run_daily_quant_report()` invokes `DailyQuantOrchestrator`, the unique formal
daily entry point. The renderer receives one typed `DailyQuantResult`; it does not query providers,
calculate factors, rank stocks, resize positions, or invent actions.

## Effective configuration and evidence

`EffectiveRuntimeConfig` is resolved once using `defaults -> config file -> explicit PAT_
environment -> explicit CLI override`. ApplicationService, data services, calendar, strategy,
portfolio, risk, cost, doctor, diagnostics, and terminal receive this object or an immutable
projection. `config.yaml` cannot contain holdings; the real portfolio ledger is the only
holdings/cash source.

The run records separate deterministic identities for runtime configuration, strategy parameters,
data version, portfolio constraints, risk model, transaction-cost model, and approval artifact.
Each stage manifest binds its canonical input/output and the previous stage output. The run
certificate binds the final chain root.

## Gates, portfolio and risk

Calendar, Data, PIT, Feature, Factor, Signal, Probability, Portfolio, Risk, Decision, Execution,
and Persistence emit explicit status, duration, message and metadata. A hard failure makes the run
non-actionable and empties executable legs. Production calendar errors never fall back to weekday
guesses; deterministic fallback is an explicit test/development option only.

Portfolio construction requires the Model Registry and an immutable `PortfolioValidationArtifact`
to match exact Alpha/data/strategy/constraint/risk/cost/runtime/benchmark fingerprints. The risk
identity includes governed stress thresholds. Probability calibration is a separate Locked-OOS
artifact; model approval and factor coverage never imply calibrated probability.

Production correlation risk compares a recent window with a strictly earlier historical baseline
at the same decision cutoff. Missing history is `NOT_VALIDATED`, never a fabricated zero. Size
exposure uses PIT market cap when certified; otherwise the constraint is explicitly not validated.
Sector/size neutralization persists sample coverage, group sizes and degrees-of-freedom status.

## Manual execution boundary

The portfolio is a real manual ledger. ACCEPT creates a pending manual-execution record only. One
recommendation can have multiple immutable Schwab fills and restart-safe
`PENDING/PARTIAL/FILLED/CANCELLED/MODIFIED` aggregate state. Holdings and cash change only for the
actual filled quantity. There is no broker connector, automatic order submission, paper account,
or simulated fill workflow. Historical backtesting is separate and retained.

## AI and runtime boundaries

AI receives only completed deterministic evidence when explicitly enabled. It cannot calculate
factors, rank securities, change target weights, veto risk, generate BUY/SELL, or write an execution
plan. AI failure never degrades Quant readiness.

The Windows console executable is the only product UI. It does not contain Streamlit, Textual,
Electron, React, Node, a browser launcher, or a localhost API bridge. User data is written only
below `%LOCALAPPDATA%\PersonalAlphaTerminal`.
