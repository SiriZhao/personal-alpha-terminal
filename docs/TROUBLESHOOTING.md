# Troubleshooting

Run `PersonalAlphaTerminal.exe doctor` first. Full tracebacks are in `%LOCALAPPDATA%\PersonalAlphaTerminal\logs`; the terminal shows only a safe summary.

## DATA UNAVAILABLE

- **Symptoms:** Data stage FAIL, no final decisions.
- **Cause:** provider timeout/rate limit, network failure, schema rejection, or no cache.
- **Check:** `doctor`, then `data.log`; verify provider order and connection.
- **Fix:** retry `refresh`. Do not bypass the gate or insert fabricated prices.

## DATA STALE

- **Symptoms:** latest observation is older than the expected U.S. session.
- **Cause:** missed refresh, provider outage, stale cache.
- **Check:** DATA HEALTH expected/latest/age/source fields.
- **Fix:** refresh after connectivity returns. Stale cache remains read-only and cannot create trades.

## NO DECISION / PORTFOLIO MISSING

- **Symptoms:** `NOT_ACTIONABLE`, Portfolio gate FAIL.
- **Cause:** no real ledger, incomplete valuation, model/PIT/risk gate failure, or no worthwhile rebalance.
- **Check:** Pipeline blockers and Rejected Signals.
- **Fix:** use `portfolio-init`, preview and commit a CSV, or resolve the stated gate. A computed HOLD/NO_ACTION can be the correct result.

## NETWORK / CACHE

- **Symptoms:** primary provider fails; fallback is degraded or cache is corrupt.
- **Cause:** offline network, challenge page, partial write, checksum/schema mismatch.
- **Check:** `data.log` and cache manifest. HTML is never accepted as market CSV.
- **Fix:** restore connectivity and refresh. Delete only the identified reproducible cache file, never the database or immutable snapshots.

## CSV IMPORT

- **Symptoms:** missing column, duplicate symbol, invalid quantity/cost, unmatched security.
- **Cause:** unsupported export or ambiguous security master.
- **Check:** run preview without `--commit`.
- **Fix:** export Schwab Positions CSV again or correct a copy. Never edit the broker source in place.

## LLM ERROR

- **Symptoms:** explanation unavailable while Quant remains READY.
- **Cause:** no key, 401/429, timeout, invalid model/base URL.
- **Check:** optional AI configuration and redacted logs.
- **Fix:** disable AI or correct credentials. Quant decisions are unchanged.

## MARKET CLOSED / DATE ERROR

- **Symptoms:** closed session or unexpected trade date.
- **Cause:** weekend, U.S. holiday, early close, DST, or local clock error.
- **Check:** `doctor` timezone/calendar row and report analysis/trade dates.
- **Fix:** correct the Windows clock/timezone. Do not substitute calendar-day arithmetic.

## EXE FAIL

- **Symptoms:** window closes or STARTUP BLOCKED.
- **Cause:** incomplete extracted onedir, denied write permission, missing runtime file, disk space.
- **Check:** extract the entire ZIP to a normal local directory; inspect `boot.log` and `error.log`.
- **Fix:** do not copy only the EXE from the onedir release. Keep `_internal` beside it.

## UNICODE / NARROW TERMINAL

- **Symptoms:** missing glyphs, wrapping, or reduced charts.
- **Cause:** legacy console font/encoding or small window.
- **Check:** use Windows Terminal with a Unicode font and UTF-8.
- **Fix:** widen the window; the renderer automatically falls back to folded tables and text.
