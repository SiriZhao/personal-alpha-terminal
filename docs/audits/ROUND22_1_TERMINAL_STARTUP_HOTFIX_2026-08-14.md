# ROUND22.1 Terminal Startup / Live Refresh Non-Blocking Hotfix

Date: 2026-08-14

Verdict: `ROUND22_1_READY`

## Root cause

`run_terminal.bat` launched `main.py`, which imported the full CLI/dependency tree and then ran
`python main.py daily` synchronously: market refresh completed before the first frame was rendered.
With a broad universe refresh in progress, the window stayed blank for seconds/minutes. Redirected
stdout also used the console codepage, so even text that did print could arrive buffered or as
mojibake.

## Startup call graph (before)

```text
run_terminal.bat -> python main.py -> import terminal.cli (heavy)
  -> load_config -> ApplicationService.run_daily_quant_report(refresh=True)
  -> market refresh (blocking, no visible output)
  -> quant workflow -> render_daily_quant_result
```

## Startup call graph (after)

```text
run_terminal.bat (PYTHONUNBUFFERED=1, PYTHONUTF8=1)
  -> python -u main.py -> pure-stdlib banner (~0.2s)
  -> ConsoleInstanceLock (duplicate protection)
  -> startup panel: DB / portfolio / latest run / latest snapshot / refresh state
  -> daily refresh with progress callback (cache scan, provider batch, PIT, FACTOR)
  -> render_daily_quant_result (unchanged final render)
```

## Modified files

- `main.py` ? fast pure-stdlib startup banner before heavy imports.
- `run_terminal.bat` ? `python -u`, `PYTHONUNBUFFERED=1`, `PYTHONUTF8=1`.
- `src/personal_alpha_terminal/terminal/cli.py` ? startup panel, progress printer/heartbeat,
  `terminal-status` command, duplicate-launch lock handling.
- `src/personal_alpha_terminal/application/app_service.py` ? optional progress callback.
- `src/personal_alpha_terminal/application/daily_orchestrator.py` ? progress at refresh/PIT/FACTOR.
- `src/personal_alpha_terminal/application/data_service.py` ? progress passthrough.
- `src/personal_alpha_terminal/data/market_data/service.py` ? per-batch progress in broad refresh.
- `tests/unit/application/test_round22_1_terminal_startup.py` ? focused regressions.

## Measured timing (real Windows run_terminal smoke)

- run_terminal -> first visible output: `~232?245 ms` (after fix; before fix ~4.1 s with no
  guaranteed progress).
- Startup panel visible before refresh completes: YES (REFRESHING frame within 0.25 s).
- Live refresh smoke at 8 s: cache scan and `[Provider] ?? 1 / 13` progress visible; heartbeat
  file updated; process still alive (not black screen).
- No-refresh daily: startup panel first, full pipeline renders, DATA/PIT PASS, SIGNAL
  FAIL_BLOCKING (unchanged), 0 actions, ledger unchanged.
- Duplicate launch: second `run_terminal` prints
  `Personal Alpha Terminal is already running (PID ...)` and exits without starting a second refresh.

## Provider timeout / partial failure

No DATA/PIT contract was changed. Provider batch failures remain isolated per chunk; the terminal
now shows cache scan and batch progress instead of a blank window. Existing bounded retry/backoff
and circuit-breaker behavior is unchanged.

## Heartbeat

`var/logs/terminal-heartbeat.json` is written on every progress update with pid, current_stage,
updated_at, and processed/total when known. `python main.py terminal-status --json` reports lock,
heartbeat, latest run, latest snapshot, and latest log.

## Tests / gates

- Full pytest: `983 passed`
- quant_critical: `31 passed`
- ROUND22.1 focused tests: `13 passed` (startup panel, heartbeat, batch progress, terminal-status,
  launcher unbuffered, existing lock tests)
- Ruff: PASS
- Strict mypy: PASS (421 files)
- Secret scan: PASS
- doctor: PASS with expected `OperationalPolicy IDENTITY_MISMATCH`

## Safety

- No quant logic, Alpha, Factor, PIT contract, universe semantics, Portfolio, Risk, LLM,
  Probability, or OperationalPolicy changed.
- Fixed holdings cap remains NONE; broker/auto execution remain disabled; ledger untouched.
- No policy created/renewed; no push/tag/release.

## Remaining blockers

- Full live `python main.py daily` completion was not re-verified end-to-end (smoke was stopped
  after progress was visible); refresh performance itself remains provider-bound.
- Strategy production approval and OperationalPolicy identity mismatch remain the only gates
  blocking actionable output, unchanged from ROUND22.
