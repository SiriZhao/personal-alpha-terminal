# FINAL PRODUCTIZATION REPORT

Version: **1.1.0 — Stable Terminal Baseline**  
Release path: `release/QuantTerminal/QuantTerminal.exe`  
Scope: personal US mid/low-frequency quantitative research and manual execution support. This is not broker automation or an investment-performance certification.

## 1. Core status

- PASS: terminal-first entry, local SQLite migration, deterministic quant/risk gates, real portfolio ledger, manual decision journal and historical backtest boundary.
- Removed from product flow: paper portfolio, simulated cash/orders/fills and automatic broker execution.
- AI remains optional and explanation-only; the quant workflow operates with no API Key.

## 2. Data providers and fallback

- Order: Yahoo Finance primary, Stooq secondary for supported US stock/ETF history, local cache as a stale-checked fallback.
- Real packaged smoke: Yahoo successfully returned SPY, QQQ, AAPL, MSFT, NVDA and VIX through the final EXE. Stooq was unavailable on the test network and was reported as degraded.
- Fixed yfinance 1.5.x writable cache-location compatibility. Provider failure, malformed bars, future timestamps, duplicates, stale cache and disagreement remain explicit.

## 3. Data Safety Gate

- PASS: all providers failed plus no safe cache produces `DATA BLOCKED / NO ACTION`.
- PASS: a successful primary source can continue as degraded research when the secondary source fails.
- BLOCKED FOR EXECUTABLE ACTIONS: free price data does not certify PIT corporate actions, historical universe, delistings and independent source agreement. The real smoke quality floor was 87.2/100, but the corporate-action and model gates correctly prevented BUY/SELL/ADD/REDUCE.

## 4. TUI and Daily Workflow

- PASS: `QuantTerminal.exe` opens the Textual Today screen without a browser.
- PASS: clean user directory, Chinese/space path, missing AI key, empty cache, empty portfolio, Doctor, restart and fail-closed Daily.
- PASS: Today separates system/data/model/portfolio status and hides provider tracebacks from normal output. Technical details go to rotating logs.

## 5. Nasdaq 23H readiness

- PASS: centralized `LEGACY_US_EQUITY` / `NASDAQ_23H` feature flag, effective date, DST-aware America/New_York calendar and next-trade-date night mapping.
- Night execution remains disabled. Missing night data is an unavailable information feature, never fabricated market data.

## 6. Portfolio and manual execution

- PASS: create/list portfolio, generic/Charles Schwab snapshot import, ACCEPT/REJECT/WATCH, Pending Manual Execution and manual fill entry.
- PASS: a manual fill atomically writes the immutable transaction and synchronizes cash/current position. Duplicate fill is idempotent; insufficient cash, oversell and backdating behind a newer snapshot are rejected.
- Final packaged ledger smoke: cash `100000.0000 -> 97987.0000`, AAPL quantity `10.00000000`, source `manual_charles_schwab`.
- There is no Charles Schwab or other broker order API in the runtime.

## 7. Verification

- Main automated suite: **484 passed, 0 failed, 0 skipped**.
- PostgreSQL backup group: sandbox ACL produced 3 environment failures; the same group rerun outside the ACL sandbox was **7 passed**.
- Combined verified tests: **491 passed, 0 failed, 0 skipped**.
- Ruff: PASS. Mypy strict: PASS across 373 source files. `pip check`: PASS.
- Two non-failing `SyntaxWarning` messages originate from the third-party Backtrader package under Python 3.14.

## 8. Packaged release smoke

- PASS: first launch, database migration, TUI start, Doctor, portfolio creation/list, cache miss, fail-closed offline Daily, real Yahoo fetch, AI unavailable, ACCEPT/REJECT/WATCH, manual fill, restart, logs and Chinese/space user path.
- PASS: ZIP opens successfully and contains 8,448 entries.
- Runtime: Windows 11 x64, bundled CPython 3.14.3, PyInstaller 6.21.0 onedir.
- No `QuantTerminal` process was left running after validation.

## 9. Size and retention

- Project before cleanup: **4,114,445,526 bytes (3.832 GiB)**.
- Project after cleanup: **626,145,880 bytes (0.583 GiB)**.
- Removed only regenerable old builds, distributions, test sandboxes, caches, reports, Python bytecode and the project virtual environment. Source, tests, migrations, final release, database, configuration and market data were preserved.
- Logs rotate at 5 MB with 3 backups. Reports retain 180 days; diagnostics and update artifacts retain 30 days. Database, portfolio, configuration and audit snapshots are excluded from automatic retention.

## 10. Release artifacts

- EXE: `release/QuantTerminal/QuantTerminal.exe`
- ZIP: `release/QuantTerminal-v1.1.0-win64.zip`
- EXE SHA256: `5f8e2df076fd356b9063544dc108ffc319dc1f0ac14a5a79a2ec36c02b7f0788`
- ZIP SHA256: `75b816ac58651a5d605084561f63808ad5665c4d68a52678133af740edeab0fc`

## Known issues / risks

1. **HIGH — real-action gate remains blocked:** PIT corporate actions, historical constituent universe, delistings and professional independent source certification are incomplete. Do not treat the terminal as production-approved for capital deployment.
2. **HIGH — no production-approved Alpha evidence:** the terminal will correctly emit `NO ACTION` until a model passes locked OOS/walk-forward promotion gates.
3. **MEDIUM — free-provider concentration:** Stooq was unavailable in the final network smoke and does not cover VIX; Yahoo was the only successful live source. Free-source outages can leave Daily in read-only/cache mode.
4. **MEDIUM — independent environment scope:** validation used a clean local user-data directory on the current Windows 11 host, not a separate pristine Windows VM.
5. **MEDIUM — database recovery scope:** PostgreSQL backup logic tests pass, but no real PostgreSQL corruption/restore RPO/RTO exercise was performed in this release cycle.
6. **LOW — unsigned executable:** the binary has no commercial code signature; Windows SmartScreen may show Unknown Publisher.

Release decision: **suitable as a fail-closed personal research/manual-recording baseline; not Production Approved for autonomous or unreviewed investment decisions.**
