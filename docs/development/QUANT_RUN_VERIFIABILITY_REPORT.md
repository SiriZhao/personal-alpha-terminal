# Quant Run Verifiability Report

Date: 2026-08-09  
Version: 1.1.0  
Status: IMPLEMENTED_FIXTURE_TESTED / REAL DATA RUN FAIL-CLOSED

## 1. Original root causes

- The cold/incomplete database refresh requested only the incremental overlap window, so the
  newest manifest contained six bars per symbol even when the strategy required 496.
- `quality=partial` combined unrelated meanings: insufficient history, single-source lineage,
  and uncertified corporate actions. The terminal exposed that as a generic warning.
- A missing portfolio caused an early return before the research-only PIT/factor/alpha path.
- An empty decision list was rendered as `NO_ACTION` even when required stages had not run.
- Raw latest-date evidence and the absent PIT cutoff were rendered as contradictory data dates.
- A blocking data exception rolled back the sync manifest and current-universe members while
  leaving a file manifest behind.
- Duplicate count was populated from updated rows instead of actual duplicate observations.

## 2. Core changes

- Added explicit stage semantics: `PASS`, `PASS_DEGRADED`, `FAIL_BLOCKING`, `NOT_RUN`.
- Added `DailyDataCertifier` with required/optional universe coverage, history, freshness,
  OHLC, future-row, duplicate, lineage, adjustment, and corporate-action diagnostics.
- Cold databases now request the full configured history; sufficiently populated databases use
  only the overlap window.
- Split `ProductionDailyQuantInputAssembler` into research assembly and portfolio completion,
  while retaining one canonical production adapter.
- Removed the portfolio early return. Missing portfolio blocks portfolio/risk/decision/execution,
  but does not suppress independent research stages when data gates pass.
- Data sync evidence commits before a fail-closed quant gate is evaluated. Current minimum-universe
  snapshots are populated idempotently, including repair of an existing empty snapshot.
- Added immutable per-stage manifests plus one `run_certificate.json`, all materialized from the
  same `DailyQuantResult`; no renderer or certificate path recalculates decisions.
- Added deterministic decision traces and `explain SYMBOL` over the persisted certificate.
- Added `portfolio-init`, `portfolio-import`, `portfolio-show`, validation, and explicit manual-only
  Charles Schwab semantics.
- The terminal now has dedicated Data Certification and PIT/Universe evidence sections and never
  renders `NO_ACTION` for an incomplete run.

Primary files:

- `application/data_certification.py`
- `application/data_service.py`
- `application/daily_orchestrator.py`
- `application/daily_result.py`
- `application/quant_daily_service.py`
- `quant_engine/input_assembler.py`
- `terminal/cli.py`
- `terminal/daily_renderer.py`

## 3. Provider state

- Primary actually used: Yahoo Finance (`yfinance` typed stock/ETF/index adapters).
- Configured fallback capability: Stooq for US stocks and ETFs only.
- Latest real refresh: 18 requested, 18 received, 15/15 required symbols met the history and
  freshness threshold.
- Stooq was not used in this successful Yahoo refresh and is not independent confirmation.
- Cross-provider reconciliation remains `NOT_CERTIFIED`.
- Corporate-action PIT ledger remains `NOT_CERTIFIED`.

## 4. Real pipeline stage matrix

| Stage | Status | Evidence |
|---|---|---|
| CALENDAR | PASS | Analysis 2026-08-07; next trade date 2026-08-10 |
| DATA | FAIL_BLOCKING | Corporate actions and independent reconciliation uncertified |
| PIT | NOT_RUN | Blocked by DATA |
| FEATURE | NOT_RUN | Blocked by DATA |
| FACTOR | NOT_RUN | Blocked by DATA |
| SIGNAL | NOT_RUN | Blocked by DATA |
| PROBABILITY | NOT_RUN | Blocked by DATA |
| PORTFOLIO | NOT_RUN | Portfolio preflight reports NOT_INITIALIZED |
| RISK | NOT_RUN | Blocked by DATA and missing real portfolio |
| DECISION | NOT_RUN | No trading judgment generated |
| EXECUTION | NOT_RUN | No Schwab execution list generated |
| PERSISTENCE | PASS | Certificate and all stage manifests saved |

Classification: `INVALID_NON_ACTIONABLE`  
Trading use: `DO_NOT_USE_FOR_TRADING`

## 5. Actual data coverage

- Snapshot: `US-20260809T025148Z-a54c93f92532`
- Raw canonical rows in desktop DB: 9,037
- Expected minimum required bars: 7,440
- Required-strategy bars received/valid: 7,531 / 7,531
- Coverage: 100%
- Latest timestamp: 2026-08-07 20:30:00+00:00 (normalized UTC availability time)
- Missing required symbols: 0
- Stale required symbols: 0
- Invalid OHLC rows: 0
- Duplicate observations: 0
- Future-available rows: 0
- Timezone violations: 0
- Current dated universe snapshot: 18 members, with explicit availability time; this does not
  certify historical constituent membership.

## 6. PIT and look-ahead result

- Raw future-timestamp certification check: PASS (0 future rows).
- Automated PIT/look-ahead, future timestamp, stale data, universe, corporate-action leakage,
  and benchmark-cutoff regressions: PASS.
- Real PIT total-return versions/points: 0/0, so the real PIT stage is correctly blocked.
- Historical survivorship-safe membership and corporate-action ledger are not certified. No
  current-survivor replay or provider adjusted-close substitution was used.

## 7. Factor and signal result

- Real run factor observations: 0.
- Real run eligible/positive/negative signals: 0/0/0.
- Reason: the DATA hard gate stopped the production assembler before PIT/factor/model execution.
- Fixture E2E proves the same production adapter can produce factors, target portfolio, risk,
  decisions, execution plan, decision trace, and certificate. This is not real-data Alpha proof.
- Conditional probability remains `NOT CALIBRATED OOS` and has zero position influence.

## 8. Portfolio and risk

- Real desktop portfolio: `NOT_INITIALIZED`.
- The CLI exposes validated bootstrap/import/show commands. No portfolio was created automatically.
- NAV, target weights, risk, turnover, and execution are therefore unavailable in the real run.
- `ACCEPT` cannot place a broker order; Charles Schwab execution remains manual only.

## 9. Benchmark

- Real benchmark status: `UNAVAILABLE` because certified PIT total-return data did not pass.
- The production adapter and regression tests enforce the same decision cutoff for strategy and
  benchmark. No proxy benchmark result is displayed as certified.

## 10. Verification

- Full pytest suite: 482 passed.
- Ruff: passed.
- mypy strict: passed for 339 source files.
- pip check: no broken requirements.
- `git diff --check`: passed (line-ending notices only).
- Targeted tests cover complete data, optional degradation, required-data blocking, future/stale
  data, insufficient universe, missing portfolio with research continuation, complete NO_ACTION,
  invalid-run NOT_ACTIONABLE, benchmark PIT consistency, certificate consistency, persistence
  reload, terminal provenance, and sync-evidence transaction durability.

## 11. Remaining limitations

1. No independently reconciled second source for all required US assets; Stooq lacks index coverage
   and was not used by the successful refresh.
2. No certified PIT corporate-action ledger or PIT total-return versions.
3. No certified historical constituent/delisting membership for survivorship-safe backtests.
4. No real portfolio has been initialized/imported.
5. No real-data locked-OOS model approval exists in the desktop DB; strategy registration is
   reached only after data gates pass and cannot self-promote.
6. Therefore this build is not approved for a manual-money pilot. It is safe for continued data
   certification and fixture-tested engineering validation only.

## 12. Final real daily run

- Run ID: `daily-594fc637fe834f4e959cdacb9a9bff00`
- Certificate:
  `reports/daily-runs/daily-594fc637fe834f4e959cdacb9a9bff00/run_certificate.json`
- The directory also contains one manifest for every formal stage.
