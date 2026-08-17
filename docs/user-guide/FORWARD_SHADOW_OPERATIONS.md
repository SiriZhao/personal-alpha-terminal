# Forward Shadow Operations Runbook

This runbook starts real Forward Shadow evidence collection without granting
the LLM production authority.

## Invariants

```text
Production source = Quant-only
Production lambda = 0
LLM formal economic influence = 0%
Manual confirmation = enabled
Automatic promotion = forbidden
```

## One-Time Operator Configuration

Configure the scheduler or terminal process explicitly. Do not commit secrets.

```powershell
$env:PAT_RUNTIME_PROFILE = "FORWARD_SHADOW_VALIDATION"
$env:PAT_LLM_PROVIDER = "deepseek"
$env:PAT_AGENTIC_SHADOW_EXTERNAL_ENABLED = "true"
# DEEPSEEK_API_KEY must already be available from the approved secure environment.
```

An API key by itself does not enable external calls.

Verify configuration without a paid call:

```powershell
.\.venv\Scripts\python.exe main.py forward-shadow provider-status
.\.venv\Scripts\python.exe main.py forward-shadow doctor
```

Use the live provider test only for setup or provider/model changes. It never
enters Forward evidence:

```powershell
.\.venv\Scripts\python.exe main.py forward-shadow provider-test --live
```

## Daily

Run after the intended completed market session and PIT data cutoff are valid.
The standard command automatically uses the Forward Shadow operations service
when the explicit profile is active:

```powershell
.\.venv\Scripts\python.exe main.py daily
```

Equivalent explicit command:

```powershell
.\.venv\Scripts\python.exe main.py forward-shadow run
```

Confirm in the summary:

```text
Quant Production = PASS or an honest Quant blocker
Agentic Shadow = COMPLETE / DEGRADED / FAILED
Manual action list = UNCHANGED BY LLM
Production LLM authority = 0%
Production lambda = 0
```

Do not force a run when the market session is incomplete, the PIT cutoff is
uncertain, or required real data is unavailable.

## Scheduled or Periodic Outcome Collection

This command is idempotent and suitable for Windows Task Scheduler, cron,
systemd timers, or manual use. Scheduling time remains operator configuration.

```powershell
.\.venv\Scripts\python.exe main.py forward-shadow collect-outcomes
.\.venv\Scripts\python.exe main.py forward-shadow reconcile
.\.venv\Scripts\python.exe main.py forward-shadow status
```

No matured outcome is a successful no-op. Missing exact-session data remains
pending; unsafe provenance remains blocked and excluded.

## Recovery

Inspect current state:

```powershell
.\.venv\Scripts\python.exe main.py forward-shadow status --json
.\.venv\Scripts\python.exe main.py forward-shadow reconcile --json
```

Resume the latest compatible incomplete run:

```powershell
.\.venv\Scripts\python.exe main.py forward-shadow resume
```

Resume a specific run:

```powershell
.\.venv\Scripts\python.exe main.py forward-shadow resume --run-id <shadow_run_id>
```

If the command reports `BLOCK_REQUIRES_NEW_RUN`, code, provider, or model
provenance changed. Do not rewrite the immutable prediction; start a new valid
session run instead.

## Never Do

```text
Do not edit ledger rows manually.
Do not backfill historical runs as real Forward evidence.
Do not count tests, fixtures, synthetic data, smoke tests, or backtests.
Do not force an outcome before its XNYS horizon matures.
Do not use closest-record matching.
Do not combine incompatible provider/model/schema populations silently.
Do not force promotion.
Do not set a non-zero production lambda.
Do not allow LLM output to alter production weights, orders, or risk limits.
```
