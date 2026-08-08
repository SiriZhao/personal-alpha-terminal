# Terminalization Stage 1 Report

Date: 2026-08-09
Scope: Quant backend to terminal final-decision closure; no release packaging and no destructive frontend removal.

## 1. Actual production call chain

The default console path is now:

`console.main -> terminal.cli.run_daily -> ApplicationService.run_daily_quant_report -> DailyQuantOrchestrator -> DataService -> ProductionDailyWorkflow -> ProductionDailyQuantInputAssembler -> USAdaptiveAlphaCoreV1 -> DailyQuantPipeline -> RiskModel -> DynamicRiskBudget -> PortfolioConstructionEngine -> TradeGenerator -> DecisionEngine -> DailyQuantResult.persist -> terminal.daily_renderer`

The terminal renderer consumes one immutable `DailyQuantResult`. It does not calculate factors, weights, risk, or actions. The former path that separately ran `DailyResearchPipeline` and then attached unrelated persisted recommendations is no longer the default daily path.

## 2. Core changes

- Added the single `DailyQuantOrchestrator` application entry.
- Added a typed, serializable `DailyQuantResult` and atomic JSON run snapshots.
- Preserved same-run factor observations, portfolio prices/quantities, risk output, target, trades, benchmark sample, data cutoff, and provenance from the canonical production pipeline.
- Added explicit stage gates: `CALENDAR`, `DATA`, `PIT`, `FEATURE`, `FACTOR`, `SIGNAL`, `PROBABILITY`, `PORTFOLIO`, `RISK`, `DECISION`, `EXECUTION`, and `PERSISTENCE`.
- Kept conditional probability at `SKIPPED / INSUFFICIENT EVIDENCE` with zero position influence when no validated PIT/OOS overlay exists.
- Kept the real-portfolio rule: a missing portfolio never implies an empty portfolio and never creates an initial buy list.
- Kept AI optional and outside all deterministic calculations.
- Kept Charles Schwab as manual execution only; no broker API is called.

## 3. DailyQuantResult structure

The snapshot includes run/version/timestamps, analysis and trade dates, market session, data cutoff, stage results and durations, data-health rows, regime status, factor rows, conditional evidence, candidates, real portfolio snapshot, risk summary, final decisions, rejected signals, manual execution plan, benchmark evidence, blockers/warnings, configuration hash, model versions, and provenance.

Only `final_decisions` may populate the formal BUY/SELL area. Diagnostic factors and candidates are explicitly labelled `CANDIDATE != TRADE` or `DIAGNOSTIC ONLY`.

## 4. Pipeline gates

- Hard `DATA`, `PIT`, `PORTFOLIO`, `RISK`, `DECISION`, `EXECUTION`, or `PERSISTENCE` failures result in `NOT_ACTIONABLE`.
- A failed run contains diagnosis and rejected-signal reasons but has no final decisions or execution legs.
- Data-health rows identify expected/latest date, source, coverage/missingness when available, and the technical reason.
- Uncalibrated regime output is not presented as probability.
- A persistence failure revokes actions rather than returning an unrecorded proposal.

## 5. Terminal entry

Default no-argument console startup now runs `daily`; the prior Textual fullscreen application remains available only to the existing compatibility smoke path during Stage 1.

Formal CLI commands now include `daily`, `refresh`, `data`, `portfolio`, `portfolio-init`, `portfolio-import`, `factors`, `probability`, `risk`, `decisions`, `backtest`, `doctor`/`diagnostics`, `settings`, `version`, and manual decision/fill commands.

The Rich renderer displays the complete Today Quant Report directly. At widths below 100 columns it uses compact data, factor, probability, and decision columns instead of failing or producing unusable wide tables.

## 6. E2E and regression results

- Repository test inventory: 515 tests.
- Core unit groups: passed.
- PostgreSQL backup and optional VectorBT/Backtrader backend group: passed in the required unrestricted filesystem/JIT environment.
- Integration, dashboard compatibility, and performance groups: passed.
- Stage 1 tests verify real `DailyQuantPipeline` output reaches the renderer without recalculation, missing portfolio and stale/PIT/risk failures are closed, weekend/DST handling is correct, LLM-disabled operation works, narrow rendering works, and persisted decisions match the same `DailyQuantResult`.
- Real CLI cold/empty-database smoke: passed with `DATA FAIL`, `NOT_ACTIONABLE`, no execution legs, exit code 3, and a persisted diagnostic JSON snapshot.
- Ruff: passed.
- mypy `--strict`: passed.
- `pip check`: passed.

Passing fixtures prove implementation behavior, not real-data Alpha validity. Current production action remains blocked unless certified PIT data and an exact locked-OOS model approval are present.

## 7. Remaining legacy frontend and dependencies

Still retained for Stage 1 compatibility:

- `src/personal_alpha_terminal/tui/` Textual fullscreen screens.
- `src/personal_alpha_terminal/dashboard/` and Streamlit entry/configuration.
- The legacy terminal research modules `terminal/pipeline.py`, `terminal/report.py`, provider/cache helpers, and their compatibility tests.
- Streamlit/Textual and optional research-backend dependency declarations required by retained legacy entrypoints/tests.

None of these components is the default daily decision path after this change.

## 8. Stage 2 deletion candidates

After Stage 2 reconfirms command coverage and migration compatibility, it can safely evaluate removal of:

- the Textual screens and default-TUI compatibility branch;
- Streamlit dashboard pages and `.streamlit` configuration;
- the legacy `DailyResearchPipeline` presentation/report path and `_attach_authorized_candidates` compatibility helper;
- UI-only tests and runtime dependencies that no longer serve the terminal product.

Deletion must retain the application services, canonical data/PIT contracts, quant engine, historical backtest, real manual portfolio ledger, Schwab CSV import/manual fill workflow, diagnostics, and audit snapshots.

## Current safety status

- Backend-to-terminal chain: implemented and fixture/E2E tested.
- Real market download capability: available through existing providers, with fail-closed behavior.
- Certified PIT historical universe/corporate actions/fundamental revisions: dependent on actual certified evidence in the selected runtime database.
- Locked-OOS production Alpha approval: not inferred from tests and not automatically promoted.
- Automated brokerage execution: disabled and absent from the daily path.
