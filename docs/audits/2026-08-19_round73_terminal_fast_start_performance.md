# ROUND73 — Terminal Fast-Start & Pipeline Performance Closure

Date: 2026-08-19
Starting commit: `9bca56e0f87231b7169d61f3782af9d060bef658` (`ROUND72: close forward shadow and paper readiness`)

## Scope and preserved state

The starting working tree already contained user/inherited changes to `.gitignore`,
`src/personal_alpha_terminal/quant_engine/alpha_engine2/deflated.py`,
`tests/unit/quant_engine/alpha_engine2/test_shadow_and_deflated.py`,
`tests/unit/test_terminal_cli.py`, and
`docs/audits/2026-08-17_FINAL_FLAGSHIP_AUDIT_CLEANUP_STRESS_TEST.md`.
They were preserved. No reset, clean, deletion of ledgers/configuration, broker action,
or remote push was performed.

The production invariants remain unchanged: long-only; manual confirmation;
`AUTO_EXECUTION=DISABLED`; no broker submission; Classical/Production Quant Champion
unchanged; no fixed pre-optimizer Top-N or holdings cap added; LLM and Probability
formal influence remain zero; Alpha Engine 3 and Adaptive Exposure remain challengers.

## Root cause

The observed >20-minute apparent freeze had four independent contributors:

1. The normal `main.py` / `daily` path synchronously ran remote refresh, PIT,
   factor, optimizer/risk, optional LLM/news, and Shadow work before returning a
   usable terminal frame.
2. Cache planning mixed the current Nasdaq-directory observation date with an IPO
   date. That made legacy new-listing state unsafe; young histories could be
   repeatedly classified for impossible backfill. Non-stock assets were also sent
   the stock bootstrap window, re-requesting persisted ETF/index history.
3. A warm refresh still used overlapping sessions for individual non-stock assets.
   This could re-request already persisted ranges such as `2026-08-15` through
   `2026-08-18` without a new trading session.
4. Optional branches were on the hot path: an unverified external LLM could spend
   its inherited timeout/retry budget, and disabled Agentic Shadow work could still
   build a full zero-effect challenger artifact/counterfactual ledger.

The latest no-new-session evidence disproves a real cache miss: the direct cache
progress line is `4238 / 4957`, while the complete provider accounting is 5,027
historical histories reused, 717 young listings safely deferred, 2 permanent
provider-no-history symbols, and zero provider requests. The 719 deferred symbols
are not safe refresh candidates for this session and must not be redownloaded.

## Implementation

- Added a two-phase normal launch. Phase A reads only bounded local state and
  renders the terminal. Phase B is a detached, single-instance refresh worker.
- Added fail-closed terminal states: `READY_CURRENT`, `READY_STALE`, `REFRESHING`,
  `DEGRADED`, and `BLOCKED`. Stale cached output is informational only; it cannot
  become actionable before current gates complete.
- Added atomic worker state, progress, PID, elapsed time, last-progress time, and
  a 600-second total watchdog. Permission failures report the exact operation/path
  and never substitute a production database.
- Added `PAT_TERMINAL_RUNTIME_DIR` for portable worker state in restricted
  environments without changing the production database path.
- Made broad-market backfill session-aware and provenance-aware; removed the forced
  non-stock bootstrap request; removed automatic overlap re-downloads; retained
  idempotent provider persistence and bounded provider retry/timeout behavior.
- Added exact warm-result reuse only when runtime config and completed market
  session match. An immediate same-session launch does not start a worker.
- Gated optional external LLM calls on a positive connectivity result. With
  `agentic_shadow_external_enabled=false`, normal daily work now records a truthful
  deferred Shadow status rather than running disabled challenger work; explicit
  Forward Shadow operation remains the route for that challenger.
- Added low-overhead `perf_counter` profiling for data segments, PIT build,
  factor-and-alpha, probability/candidate preparation, portfolio inputs, and
  optimizer/risk. The machine-readable artifacts are
  `reports/validation-artifacts/terminal_fast_start_trace.json` and
  `reports/validation-artifacts/daily_performance_trace.json`.

## Measured evidence

All measurements below are local real-entry-point measurements on 2026-08-19.
The production terminal is premarket and the latest completed US session is
2026-08-18. No new market session existed between the back-to-back runs.

| Metric | Before | After | Delta |
| --- | --- | --- | --- |
| terminal usable time | operator observed >20 min blocking | 4.868s fresh; 5.048s immediate reuse | removed from critical path |
| foreground blocking time | refresh/PIT/factor waited in foreground | 0.480s bounded local work on current reuse | refresh is backgrounded |
| DB local fast-start read | not separately instrumented | 0.108s | measured |
| cache check / sync planning | `0 / ~4957` interpreted as refresh pressure | 0.608s provider-sync/planning; 0 requests | no bulk redownload |
| provider requests | about 11 batches reported | 0 | -100% for no-new-session run |
| provider wall time | part of >20 min wait | 0.608s local sync/planning; no network rows | provider not on warm path |
| PIT build | opaque/freeze-prone | 12.542s | measured, backgrounded |
| factor + alpha | opaque/freeze-prone | 3.005s | measured, backgrounded |
| optimizer + risk | opaque/freeze-prone | 67.747s | measured, backgrounded |
| cache hit ratio | apparent 0% from the partial counter | 5,027 / 5,027 historical histories reused (100%); 0 missing-cache symbols | corrected accounting |

Full profiled worker (`daily-fd4aa897b2134503b52b93866fffdcfe`):

- total refresh/analysis wall time: 196.966s (under the 5-minute target);
- data stage: 18.456s, including 17.026s immutable manifest/certification
  persistence, 0.608s cache/provider-sync planning, 0.150s universe snapshot,
  0.004s exchange calendar;
- LLM intelligence: 0.007s (optional/unavailable); AI brief deterministic
  fallback: 17.582s; ETF sleeve: 0.505s; news acquisition: 2.037s;
- 4,308 directly current cached symbols, 719 safely deferred, no provider rows
  returned, no duplicates, no future rows, and required-core certification 100%;
- data as-of: 2026-08-18; decision is manual-only, broker API disabled.

Run sequence:

1. **First full no-new-session worker:** normal `main.py` became usable in 4.868s;
   background analysis completed in 196.966s with zero provider requests.
2. **Immediate second same-session run:** normal `main.py` became usable in 5.048s;
   the performance trace timestamp did not change and no worker/provider refresh was
   launched. The terminal reported: `复用已验证结果，未启动重复刷新`.
3. **Explicit diagnostic no-refresh run:** `main.py --no-refresh daily` completed
   in 222.179s without remote market refresh. It deliberately renders cached output
   as non-actionable because diagnostic replay is not a current-decision grant.

The exact user launcher was inspected: `run_terminal.bat` invokes the project
`.venv` with `-u`, `PYTHONUNBUFFERED=1`, and no broker or execution command.

## Validation

- `main.py doctor`: PASS; DB, migration, calendar, portfolio, cache, reports, and
  manual-only/broker-disabled posture were verified. The historical timing was 9.1s.
- `main.py forward-shadow status --json`: PASS; production LLM influence `0%`,
  production source `QUANT_ONLY`, and no forward-evidence promotion claim.
- focused ROUND73/cache/timeout/progress/permission tests: 41 passed.
- affected terminal and market-data suites:
  `tests/unit/terminal`, `tests/unit/data/market_data`,
  `tests/unit/application/test_round22_1_terminal_startup.py`, and
  `tests/unit/test_terminal_cli.py`: 73 passed.
- timezone/session smoke: 4 passed.
- Ruff: PASS.
- strict mypy on all changed production modules: PASS.
- secret scan: `SECRET_SCAN_PASS`.

The repository's normal `.pytest_cache`, `.ruff_cache`, and default temp paths are
ACL-restricted in this automation environment. Test/static caches were redirected to
`%TEMP%`; production behavior was separately verified with elevated local filesystem
access. This is an environment permission distinction, not a fallback DB or a product
data-path change.

## Verdict

**ROUND73 = PASS.**

The normal terminal is usable in under the 10-second hard ceiling, remote refresh is
off the startup critical path, stale output is fail-closed, duplicate same-session
downloads are prevented, progress/watchdog state is visible, and the measured full
warm no-change analysis is under five minutes. No broker order was submitted.
