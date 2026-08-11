# Data Certification Final Report

Version: 1.1.0

Validation date: 2026-08-09

Result: **implementation complete; latest real-data run remains INVALID / NON-ACTIONABLE**

## 1. Root causes

- `corporate_action_certified` and `provider_reconciled` were previously default booleans; the daily updater did not produce the evidence needed to set them.
- Provider fallback was first-success routing, not independent reconciliation. Stooq currently returns an HTML/JavaScript browser challenge, which the old adapter could mistake for a CSV response.
- `Certified 15 / 18` was not a certification result: the old display counted only 15 required assets and silently omitted the three optional assets `JPM`, `JNJ`, and `XOM`.
- `7440 expected` was a minimum-history threshold (`15 required assets × 496`), not an exact exchange-calendar expectation. `7531 received` was `15 × 502` valid sessions plus one Yahoo VIX observation on a non-XNYS session. The percentage was capped at 100%, hiding over-supply.
- PIT cutoff was suppressed whenever the aggregate data gate failed even though the latest completed session and availability timestamps were known.
- Corporate-action announcement timestamps were required by the schema even though the free Yahoo endpoint does not provide reliable first-publication timestamps. That encouraged an invalid assumption rather than an explicit unknown value.

## 2. Main changes

- Added `application/data_lineage_certification.py` as the single evidence builder for corporate actions, cross-provider reconciliation, exact calendar coverage, and PIT cutoff.
- Reworked `application/data_service.py`, `application/data_certification.py`, and `application/daily_orchestrator.py` so the immutable snapshot, stage metadata, run certificate, and terminal all consume the same evidence.
- Added centralized, versioned reconciliation tolerances in `core/config.py`.
- Hardened the Stooq adapter to reject HTML/JavaScript challenges before CSV parsing.
- Added forward-only Alembic revision `c3f4a5b6d7e8`; unknown announcement dates are nullable rather than fabricated. Historical revisions were not edited.
- Updated PIT total-return/backtest contracts for an explicit unknown announcement timestamp.
- Expanded the terminal evidence to show primary-valid, secondary-checked, certified/rejected symbols, exact matched/unexpected/missing/rejected bars, rejected ticker reasons, and the PIT convention.
- Kept portfolio state separate: a missing portfolio blocks Portfolio/Decision/Execution, not market-data diagnosis.

## 3. Corporate-action certification

- Supported event types: cash dividend, split, reverse split. Symbol/ticker changes remain a security-master event and are not fabricated from the Yahoo action response.
- Raw OHLCV, display adjusted close, and corporate actions remain separate. Yahoo adjusted close is research/display-only and is not re-adjusted by the action ledger.
- Each event records symbol, type, effective date, optional announcement timestamp, actual ingestion availability, value/ratio, source, and retrieval time.
- Conservative free-source PIT policy: when announcement/first-publication time is unavailable, `announcement_at` remains null and the event becomes visible only at actual ingestion time. It is never backdated to its effective date.
- The latest real certificate checked 18 symbols, found 152 cash-dividend events in the requested two-year window, reported zero validation errors, and returned `PASS`. Split and reverse-split behavior is covered by deterministic tests; no split occurred in this particular live window.
- This certificate is valid for the current daily decision cutoff. It does **not** certify historical revision/announcement completeness for past backtests.

## 4. Independent reconciliation

- Primary: Yahoo Finance raw daily OHLCV/index levels.
- Secondary stocks/ETFs: Stooq adapter.
- Secondary VIX: the CBOE Global Indices VIX historical CSV.
- Comparison aligns XNYS sessions and compares normalized daily-return paths, not raw absolute prices with incompatible adjustment conventions.
- Configured evidence statuses are `PASS`, `PASS_WITH_WARNING`, `FAIL_BLOCKING`, and `UNAVAILABLE`. Sparse large divergences below the configured aggregate blocking ratio are now explicitly `PASS_WITH_WARNING`, never silent `PASS`.
- Current Stooq response is an HTML/JavaScript challenge. It is recorded as `UNAVAILABLE`, not parsed, retried without an infinite loop, and never converted into a passing reconciliation.

## 5. 18-symbol certification result

Latest cold-start result:

- Requested: 18
- Yahoo received / primary-valid: 18 / 18
- Independently certified: 1 (`^VIX`, CBOE; `PASS_WITH_WARNING` because two daily-return differences exceeded the per-observation blocking tolerance but remained below the configured aggregate blocking ratio)
- Rejected: 17 (`SPY`, `QQQ`, `IWD`, `IWM`, `VTI`, `TLT`, `GLD`, `SGOV`, `AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`, `META`, `JPM`, `JNJ`, `XOM`)
- Rejection reason for all 17: independent Stooq evidence unavailable due to the HTML/JavaScript browser challenge.
- Required rejected symbols block the entire strategy universe. Optional symbols are listed separately and never silently dropped into cross-sectional ranking.

The full per-symbol matrix is in the run certificate under `data_certification.symbol_matrix` and in the terminal `FAILED / REJECTED SYMBOLS` section.

## 6. Bar-count discrepancy

The old `7440 / 7531` display mixed a minimum-history threshold with an observed count. It is replaced by exact exchange-session accounting for all 18 assets:

- Expected: 9,036 (`18 × 502` XNYS sessions)
- Matched: 9,036
- Missing: 0
- Unexpected: 1 (`^VIX`, 2026-05-25, an XNYS holiday)
- Rejected/quarantined: 1
- Raw received: 9,037
- Valid PIT-input bars: 9,036
- Coverage: 100%, calculated as matched/expected without hiding the unexpected observation

The quarantined VIX observation remains in raw lineage but cannot enter PIT/features.

## 7. PIT semantics

- Analysis date: latest completed XNYS session.
- Data availability: daily bar event time plus the explicit provider-publication delay; stored timestamps are timezone-aware UTC.
- Decision time: actual daily orchestration time after refresh/evidence ingestion.
- Trade date: next valid exchange session for manual execution.
- Latest real run: analysis `2026-08-07`, data cutoff `2026-08-07T20:30:00Z`, trade date `2026-08-10`, session `CLOSED`.
- Invariant: price/action `available_time <= decision_time`; any future-available row is blocking. Benchmark data cannot use a different cutoff.
- The cutoff is available in the certificate even when downstream PIT execution is `NOT_RUN` because the independent-data gate fails. It is evidence, not a hard-coded PASS.
- Current live universe is a current daily universe. It does not certify historical constituent membership or eliminate survivorship bias for cross-sectional backtests.

## 8. Evidence artifacts

Every refresh persists stable JSON artifacts under its immutable data snapshot:

- `manifest.json`
- `corporate_action_certificate.json`
- `provider_reconciliation_report.json`
- `data_certification_matrix.json` (exact per-symbol calendar coverage)

Every daily run persists stage manifests plus `run_certificate.json`, which contains the final per-symbol certification matrix, data/config hashes, blockers, and the separate portfolio state. No secrets or API keys are included.

## 9. Automated validation (historical pre-Final-Closure checkpoint)

- Ruff: PASS (`src`, `tests`, `migrations`, `scripts`)
- mypy strict: PASS, 340 source files
- pytest: **490 passed**, 0 failed
- pip check: PASS, no broken requirements
- Covered cases include return-path reconciliation, blocking/warning tolerances, provider challenge rejection, exact under/over-supply accounting, split/dividend/reverse split, future action/price rejection, timestamp/PIT invariants, migration history, portfolio blocker separation, persisted snapshot consistency, and terminal/run-certificate consistency.

The untracked `source_audit_export/` is preserved user audit evidence and is intentionally outside the production-tree Ruff scope.

## 10. Real network validation (historical pre-Final-Closure checkpoint)

Two isolated cold-start TEST-profile runs reproduced the same result. The final run is:

- Run ID: `daily-9dae015add2f475493a88bda01cc20ad`
- Snapshot: `US-20260809T050253Z-49caf24512db`
- Data hash: `49caf24512dba9a2ef317292aaa09fd9bf1e3d16e5fe45b73a3325b567234471`
- Run certificate: `var/validation-temp/network-cold3-reports/daily-runs/daily-9dae015add2f475493a88bda01cc20ad/run_certificate.json`
- Data snapshot: `var/validation-temp/network-cold3-reports/data-snapshots/US-20260809T050253Z-49caf24512db/`
- Result: `INVALID_NON_ACTIONABLE`; zero decisions and zero execution items.

The run used a new isolated SQLite database and did not create or change a production portfolio.

## 11. Remaining limitations and actionable status

**ACTIONABLE data conditions are not satisfied.** Strict blockers are:

1. Seventeen stock/ETF symbols lack independent provider reconciliation because the existing free Stooq endpoint is currently unavailable behind a browser challenge.
2. The real portfolio is `NOT_INITIALIZED`; this is an independent user-state blocker and was not modified during validation.
3. Historical corporate-action announcement/revision completeness and historical universe membership are not certified by the free live sources; historical PIT backtests remain fail-closed where those capabilities are required.

The code no longer has an internal permanent `NOT_CERTIFIED` placeholder: it performs real evidence collection, explains every symbol, establishes a real cutoff, and fails closed on the external evidence gap. No Gate, alpha threshold, risk threshold, or strategy parameter was relaxed.

## 12. Post-Final-Closure cross-provider finalization

### Baseline and scope

- Final Closure baseline commit: `6e9bce305de417fd18c26614e7c6b008497682d3`.
- Baseline regression: **516 passed** before this incremental change.
- The existing corporate-action, canonical raw/PIT separation, exchange-calendar coverage,
  data hash, immutable evidence, benchmark cutoff and fail-closed contracts were retained.
- Alpha, factor, probability, portfolio, risk and strategy thresholds were not changed.

### Independent provider architecture

- Primary history remains Yahoo Finance raw OHLCV.
- Stock/ETF independent priority is Twelve Data official API, Alpha Vantage official API, then
  Stooq best-effort. Routing is per symbol and records every attempted provider and failure
  category.
- VIX remains Yahoo primary versus CBOE Global Indices official history.
- Stooq HTML/JavaScript challenge detection remains blocking/unavailable evidence. No browser,
  anti-bot bypass or scraping workaround was added.
- Provider state distinguishes `AUTH_NOT_CONFIGURED`, `AUTH_FAILED`, `RATE_LIMITED`, `TIMEOUT`,
  `PROVIDER_UNAVAILABLE`, `INVALID_SYMBOL`, `EMPTY_RESPONSE`, `MALFORMED_RESPONSE`,
  `SCHEMA_MISMATCH`, `API_INFORMATION`, and `LATEST_SESSION_MISSING`.

### Reconciliation and cache policy

- Secondary history uses a configured recent reconciliation window: minimum 20 and preferred
  60 XNYS sessions. It does not need to duplicate Yahoo's complete primary-history window.
- Comparison remains calendar-aligned normalized return-path evidence. It reports overlap,
  latest-session alignment, maximum/median return difference, divergence count/ratio and
  normalized latest-close-path difference.
- Latest-session equality is mandatory. A prior successful cache entry is reusable only when
  its recorded latest session exactly equals the current expected session; stale cache cannot
  certify a new run.
- Cache metadata includes provider, symbol, retrieval/as-of times, latest session, row count,
  stable content hash and schema version. API keys are excluded from URLs in diagnostics,
  artifacts, hashes and cache documents.
- Multiple independent providers can certify different symbols in one run; the first successful
  provider per symbol is used to avoid unnecessary calls and free-tier quota exhaustion.

### Evidence and terminal

- `provider_reconciliation_report.json` records the secondary candidates attempted, selected
  provider, primary/secondary latest sessions, overlap statistics, failure category and cache
  provenance for each ticker.
- Data certification reports required, optional and total certified counts independently. An
  optional rejection cannot enter cross-sectional ranking; a required rejection remains
  `FAIL_BLOCKING`.
- `data-provider status` performs preflight only. `data-provider test twelve-data` and
  `data-provider test alpha-vantage` make a single SPY authentication/schema/latest-session
  request and never run strategy or portfolio code.

### Automated validation

- Final pytest: **537 passed**, 0 failed. The Windows sandbox run used its actual sandbox ACL
  identity for PostgreSQL backup tests and `NUMBA_DISABLE_JIT=1` for the optional VectorBT
  regression; neither changes production quant logic.
- Quant critical marker suite: **31 passed**, 505 deselected, 0 failed.
- Ruff: PASS (`src`, `tests`, `migrations`, `scripts`).
- mypy strict: PASS, 348 source files.
- pip check: PASS.
- secret scan: PASS.
- New coverage includes Twelve Data ETF/success/auth/rate-limit/malformed/latest-session cases,
  Alpha Vantage compact/success/Note/Information/rate-limit/latest-session cases, per-symbol
  Twelve-to-Alpha fallback, multi-secondary symbol certification, Stooq best-effort, all-source
  failure, bounded timeout, cache freshness, response-symbol integrity, secret redaction,
  provider CLI and strict latest price-path divergence.

### Real-network validation and current blocker

- Neither `TWELVE_DATA_API_KEY` nor `ALPHA_VANTAGE_API_KEY` is configured in the current runtime.
- A cold-start attempt produced run `daily-8c6d0cdcda8048348b2387375888cc57` and persisted its
  fail-closed certificate under the isolated TEST profile. The managed execution environment
  also blocked outbound sockets (`curl error 7` / Windows socket access denied), so this run
  could not revalidate Yahoo or CBOE and is classified `INVALID_NON_ACTIONABLE`.
- Required certified: 0/15; optional certified: 0/3 in that environment-blocked attempt.
  DATA was `FAIL_BLOCKING`; PIT/Feature/Factor/Signal/Probability were `NOT_RUN`; Portfolio was
  independently `NOT_INITIALIZED`; Risk/Decision/Execution remained blocked/empty.
- The earlier unrestricted real run remains the latest evidence that Yahoo 18/18, corporate
  actions and CBOE VIX can succeed. It does not substitute for a new independent stock/ETF API
  certificate.

Current readiness is therefore **WAITING_FOR_USER_SUPPLIED_INDEPENDENT_DATA_API_KEY** and the
managed validation environment is additionally **BLOCKED_BY_ENVIRONMENT** for live sockets.
This is not a code-path failure: deterministic producer/adapter/fallback/certificate tests pass,
while the daily gate correctly refuses trading without current independent evidence. Portfolio
initialization remains a separate user action and was not performed.
