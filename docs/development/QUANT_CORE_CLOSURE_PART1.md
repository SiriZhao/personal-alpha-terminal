# Quant Core Closure / Phase I Remediation Part 1

Date: 2026-08-09  
Branch: `codex/quant-core-closure-part1`

## Status

| Workstream | Status | Evidence |
|---|---|---|
| Independent repository and baseline | DONE | Baseline commit `5ca4b19`; source SHA256 manifest and environment record saved under `docs/development/baseline/`. |
| Runtime database isolation | DONE | `RuntimeContext` binds exactly one PRODUCTION_DESKTOP, DEVELOPMENT, or isolated TEST database and rejects process rebind. |
| Alembic history | DONE | New forward revision `f9c0a1b2d3e4`; empty database upgrades to a single head. No historical revision was edited. |
| Layered US gates | DONE | Application, live, research, PIT, backtest, model, portfolio, and action states are distinct. US authorization queries US certification evidence rather than aggregate A/HK/US status. |
| US security identity and universe contracts | DONE | Symbol aliases, listing/delisting history, historical memberships, snapshots, and trading status are persisted with availability timestamps. |
| Historical stock universe certification | BLOCKED BY EXTERNAL DATA | No verified historical membership/delisting archive is present. Current-survivor replay is rejected. |
| PIT corporate actions and total return | DONE (code) / BLOCKED BY EXTERNAL DATA | Raw OHLCV, display-adjusted data, versioned PIT total-return points, and corporate-action revisions are separated. Merger/spin-off values without explicit evidence fail closed. |
| Fundamental vintage selection | DONE (code) / BLOCKED BY EXTERNAL DATA | Consumers select only filings/restatements available by the decision cutoff. Quality remains disabled without certified coverage. |
| Provider capability and challenge handling | DONE | Capabilities are explicit; Stooq HTML/challenge responses are rejected as unavailable rather than parsed as CSV. One source is not called dual-source certification. |
| Exchange sessions and tradability | DONE | Next execution open comes only from persisted verified sessions. UNKNOWN tradability cannot execute. |
| Executable strategy object | DONE | `USAdaptiveAlphaCoreV1` is deterministic, versioned, parameter-fingerprinted, and produces AlphaSignal objects only. |
| Model production approval | DONE | A model status string cannot authorize production. Approval requires a matching immutable record for locked OOS, PIT, survivorship control, and costs. |
| Production input adapter | DONE | `ProductionDailyQuantInputAssembler` is the sole certified DB-to-`DailyQuantInput` adapter. |
| Daily Alpha to Portfolio to Trade | DONE (fixture-tested) | `ProductionDailyWorkflow` runs assembler, UnifiedAlphaEngine, risk, portfolio construction, trade differences, and persists immutable results. Failures persist diagnosis only. |
| Hard-coded `NO ACTION` | DONE | Removed from the legacy terminal research pipeline. Computed HOLD/no-rebalance remains possible through the production optimizer and no-trade band. |
| Official backtest service | DONE (fixture-tested) | The application service loads raw bars, verified sessions, PIT universe snapshots, and corporate actions, then calls `ProductionBacktestEngine`. Gate failure reports missing evidence. |
| Real-data backtest / Alpha claim | BLOCKED BY EXTERNAL DATA | The production desktop database lacks certified PIT universe, corporate actions, total-return versions, and locked-OOS approval. No real Alpha claim is made. |
| Paper runtime | DONE | Current schema head contains no `paper_*` tables and active production services do not create a paper account. Real portfolio/manual execution remains separate. |

## Production chain

`RuntimeContext -> ResearchDataGate -> USPointInTimeRepository -> ProductionDailyQuantInputAssembler -> USAdaptiveAlphaCoreV1 -> UnifiedAlphaEngine -> RiskModel -> PortfolioConstruction -> TradeGenerator -> ProductionDailyWorkflow`

There is no production path from a technical indicator, AI output, UI value, or legacy QuantScore directly to BUY/SELL or target weight.

## Current real-data state

The baseline audit found two distinct legacy databases before remediation. The development database was empty; the desktop database contained a small security/price sample but no corporate actions. Both were at revision `b8a2d6f4c901`. Neither contains the evidence needed for PIT historical certification or model promotion. They were inspected, not silently merged or upgraded during this phase.

## Safety conclusion

The internal engineering reasons for permanent blocking—wrong database selection, cross-market aggregate gate, absent strategy registration, missing production adapter, stub application backtest, and hard-coded no-action—have been removed. Real action generation is still correctly blocked by external data and locked-OOS evidence. This is a Capital Preservation Objective, not a guarantee of principal or future performance.
