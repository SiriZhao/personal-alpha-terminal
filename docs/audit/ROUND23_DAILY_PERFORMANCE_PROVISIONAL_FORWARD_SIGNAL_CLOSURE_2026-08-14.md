# ROUND23 Daily Incremental Performance + Provisional Forward Signal Authorization Closure

Date: 2026-08-14

Verdict: `ROUND23_READY_FOR_OPERATOR_AUTHORIZATION`

## Before / after runtime

- Before (ROUND22 live daily): total ? 2513.62 s, refreshed 4965, cache reused 0, 13 provider batches.
- After (ROUND23 live daily, run `daily-745e8d7540544ca38a8c5678a6a86ed9`): total ? 355.67 s, refreshed 728, cache reused 4234, historical cache reused 4240, incremental refresh 6, full backfill 717, 2 provider batches observed.
- Reduction: ~86% wall-clock. Still provider/workflow-bound, but no longer a 40-minute black box.

## Root cause

The old batch path treated every symbol with a missing latest bar as requiring a full 7-day/calendar refresh and downloaded all 4,965 symbols serially. DB-bound cache classification was absent, so every daily run re-requested the same history.

## Cache semantics now

Per-symbol classification from real DB bounds:

- `CACHED_UP_TO_DATE` ? stored window covers required history and latest session.
- `INCREMENTAL_ONE_SESSION` / `INCREMENTAL_GAP` ? historical depth exists; provider is asked only for `latest+1 .. required_end`.
- `FULL_BACKFILL` ? no usable history (new listing / missing start).

Symbols sharing the same missing window are grouped into the same provider batch. Refresh accounting is persisted in the immutable data manifest (`refresh_class`) and shown in the terminal.

## Performance decomposition (live run)

- Total: 355.67 s
- DATA stage (recorded): 87.29 s
- LLM stage: 0.04 s
- Calendar: 0.14 s
- Other workflow + render (PIT/Factor/Signal/Portfolio/Risk + final render): ? 268.2 s (stage durations are not separately persisted in this build; the daily performance trace records stage-level wall time for future runs)
- Provider batches observed: 2 (batch timings propagation is fixed; the completed run predates that fix so per-batch durations are not persisted)

## Incremental refresh planner tests

- Fully current cache -> zero provider calls.
- Historical cache + one missing session -> only the missing session requested.
- Historical gap -> only the missing window requested.
- New listing -> full backfill window.
- Cache accounting (`historical_cache_reused`, `incremental_refresh_requested`, `full_backfill_requested`) is written to the manifest and terminal.

## Strategy authorization architecture

- New immutable `StrategyApproval` store with `BLOCK` / `ALLOW_PROVISIONAL_FORWARD` / `ALLOW_FULL_PRODUCTION`.
- Identity binding includes strategy, factor, alpha, universe, portfolio, risk, cost, config and code fingerprints; any core change invalidates it.
- New CLI: `python main.py strategy-approval status` and `create --decision ALLOW_PROVISIONAL_FORWARD --intent ...` (interactive only; refused under `PAT_NONINTERACTIVE`).
- Provisional-forward approval uses the same operational signal path as provisional operational policy: signals are marked `PROVISIONAL_OPERATIONAL_APPROVED` and pass the SIGNAL gate; Portfolio/Risk/Decision run through the existing pipeline while `operationally_allowed` remains tied to an effective OperationalPolicy.
- Research certification remains `NOT_CERTIFIABLE`; the terminal now shows historical research and forward strategy authorization as separate rows.
- No approval was auto-created by this round. Operator must run the two commands after code freeze.

## Gates

- Full pytest: `990 passed`
- quant_critical: `31 passed`
- ROUND23 focused: 8 + existing ROUND22.1/ROUND10 focused tests pass
- Ruff: PASS
- Strict mypy: PASS (422 files)
- Secret scan: PASS
- doctor: PASS with expected OperationalPolicy IDENTITY_MISMATCH
- `python main.py --no-refresh daily`: PASS (DATA/PIT PASS, SIGNAL FAIL_BLOCKING, 0 actions)
- `python main.py daily` (live): completed in ~356 s with new incremental planner

## Fixed holdings / safety

- fixed holdings cap: NONE
- pre-optimizer Top-N / optimizer cardinality cap: NONE
- LLM production influence: NONE
- Probability production weight: 0
- Manual-only; broker API disabled; automatic execution disabled; ledger unchanged

## Remaining blockers

- Operator must explicitly create `strategy-approval` and `operational-policy` after final code freeze.
- 717 symbols still require full backfill (new/insufficient history) and 6 required incremental refresh in the observed live run.
- Per-batch provider timings were not persisted for the completed run (fix is in place for future runs); provider-side throttling remains a possible bottleneck.
- Historical research certification remains NOT_CERTIFIABLE and is not claimed.

## Git

- No commit, push, tag, or release created this round; changes remain uncommitted on `codex/round13`.
