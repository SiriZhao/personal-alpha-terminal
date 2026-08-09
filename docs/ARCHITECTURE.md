# Current Architecture

```text
Canonical Market Data
        ↓
Point-in-Time Clean Data
        ↓
Features and Factor Observations
        ↓
Unified Alpha / USAdaptiveAlphaCoreV1
        ↓
Calibrated Conditional Evidence
        ↓
Portfolio Construction
        ↓
Risk Budget and Risk Veto
        ↓
Final Decision and Trade Difference
        ↓
Manual Execution Plan
        ↓
Immutable DailyQuantResult Snapshot
        ↓
Rich Terminal Renderer
```

`ApplicationService.run_daily_quant_report()` invokes `DailyQuantOrchestrator`, the unique formal daily entry point. The renderer receives one typed `DailyQuantResult`; it does not query providers, calculate factors, rank stocks, resize positions, or invent actions.

## Effective configuration

`EffectiveRuntimeConfig` is resolved once using `defaults -> config file -> explicit PAT_ environment -> explicit CLI override`. ApplicationService, data services, calendar, strategy, portfolio, risk, cost, doctor, diagnostics, and terminal receive this object or its immutable `Settings` projection. `config.yaml` cannot contain holdings; the real portfolio ledger is the only holdings/cash source.

The run records separate deterministic identities for runtime configuration, strategy parameters, data version, portfolio constraints, risk model, transaction-cost model, and approval artifact. The canonical run-config hash binds those identities without using volatile timestamps.

## Stage gates

Calendar, Data, PIT, Feature, Factor, Signal, Probability, Portfolio, Risk, Decision, Execution, and Persistence each emit explicit status, duration, message and metadata. Every persisted manifest has its own input/output hash and links to the previous stage output. The certificate stores the final chain root. A hard failure sets the result to non-actionable and removes executable legs.

Portfolio construction is authorized only when the Model Registry and an immutable `PortfolioValidationArtifact` match the exact Alpha/data/strategy/constraint/risk/cost/runtime/benchmark fingerprints. Missing or mismatched evidence remains fail-closed. Probability calibration is a separate Locked-OOS artifact; model approval and factor coverage never imply calibrated probability.

## Portfolio and execution boundary

The portfolio is a real manual ledger. ACCEPT records user intent only. Holdings change only after a manually entered Schwab fill. There is no broker connector, automatic order submission, paper account, or simulated fill workflow. Historical backtesting is separate and retained.

## AI boundary

AI receives only completed deterministic evidence when explicitly enabled. It cannot calculate factors, rank securities, change target weights, veto risk, generate BUY/SELL, or write an execution plan. AI failure never degrades Quant readiness.

## Runtime boundary

The Windows console executable is the only product UI. It does not contain Streamlit, Textual, Electron, React, Node, a browser launcher, or a localhost API bridge. User data is written only below `%LOCALAPPDATA%\PersonalAlphaTerminal`.
