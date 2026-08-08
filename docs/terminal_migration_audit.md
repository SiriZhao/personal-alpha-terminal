# Terminal Migration Audit

Date: 2026-08-02  
Baseline: Personal Alpha Terminal 1.0.0-test  
Baseline tests: **350 passed, 2 third-party Backtrader warnings**

## Current architecture

- Streamlit entry: `src/personal_alpha_terminal/dashboard/app.py`; Windows browser launcher: `desktop/launcher.py`.
- Core application logic already exists in repositories/services for market data, research, decision history, portfolio, backtest and daily automation, but Streamlit pages still assemble several read models directly.
- Database: SQLAlchemy + Alembic, SQLite desktop profile and PostgreSQL production profile.
- Data providers: typed asset adapters for Yahoo/AKShare and versioned local US archives. Raw, normalization and validation layers already exist.
- Data safety: `ResearchDataGate`, three timestamps, security master, universe snapshots, exchange sessions, corporate actions and PIT total-return components exist.
- Daily pipeline: isolated durable tasks, retry and a file lock exist in `automation/`.
- Paper trading: an in-memory research ledger and accepted-decision queue exist, but there is no durable cash/fill/position/valuation ledger.
- Packaging: current PyInstaller package starts Streamlit and opens a browser; it is unsuitable for the requested console product.

## Why the current gate remains missing/blocked

The inspected local database is healthy and migrated (61 tables), but its research content is empty:

- `security_master=0`, `prices=0`, `market_universe_snapshots=0`, `exchange_sessions=0`, `corporate_actions=0`.
- Five historical quality runs exist, all blocked with `sample_count=0` against `minimum_sample_size=100`.
- Consequently there is no provider lineage, immutable data version, verified US calendar, PIT universe, corporate-action completeness or certified PIT total-return series.

These are data-readiness failures, not an application/database failure. Existing UI wording conflates the aggregate research gate with overall program health.

## Required separation of readiness

The console migration will expose independent application, data, model and paper-account states. A healthy empty database will report `program=READY`, `data=EMPTY`, `model=INSUFFICIENT_DATA`, and `paper=NOT_CREATED` rather than a generic system failure.

Market-data snapshot certification will be based on actual manifest checks. Research-grade free-source data may become `CERTIFIED` for display/research when required assets pass, while portfolio-decision and PIT backtest authorization may remain blocked until universe/corporate-action requirements are satisfied.

## Logging defect

`configure_logging()` currently removes and recreates handlers and emits `application_start` on every call. Streamlit reruns call initialization repeatedly, so one process can log multiple starts. Logging configuration must become process-idempotent; a separate lifecycle function should record a start exactly once.

## Migration decisions

1. Freeze Streamlit visual development and retain it as a compatibility client.
2. Add a headless `application/` facade used by the Textual TUI and maintenance CLI.
3. Add durable snapshot manifests and paper-account ledgers through Alembic.
4. Keep all provider and research gates fail-closed; do not manufacture PIT certification.
5. Use a deterministic test provider for CI and keep DEMO storage separate from the research database.
6. Build a console-enabled PyInstaller one-folder distribution; no browser and no `--windowed` mode.

## Initial limitations

- The build host has only Python 3.14.3 installed. The console package will be verified against that exact runtime; independent Windows VM certification remains a separate gate.
- Live-provider initialization depends on network availability and provider terms. Offline development tests use deterministic fixtures that are never presented as real market evidence.
- The first console preview will not connect to a broker or submit real orders.
