# Current Status

Generated from `docs/CURRENT_STATUS.json` at `2026-08-09T16:00:00+08:00`.
This file supersedes historical release/readiness claims under `docs/reports/`.

- Version: `1.1.0`
- Git commit: `fb035499d91da8e3f234e10890dd86ae5abbd0d8+PART2_WORKTREE`
- Build ID: `SOURCE_RUNTIME`
- Evidence level: `FIXTURE_TESTED`
- Operating mode: `SHADOW_ONLY`
- Alembic head: `d4a5b6c7d8e9`

| Capability | Evidence state | Current evidence |
|---|---|---|
| DATA | `REAL_DATA_TESTED` | Primary live retrieval and certification producers ran; the required independent secondary evidence remains unavailable for most symbols. |
| PIT | `BLOCKED_BY_DATA` | Contracts and leakage tests exist; survivorship-safe universe, delistings, and historical corporate-action availability are not fully certified. |
| Alpha | `FIXTURE_TESTED` | USAdaptiveAlphaCoreV1 runs deterministically through the production adapter; this is not real Locked-OOS validation. |
| Probability | `BLOCKED_BY_VALIDATION` | Calibration artifact contract is implemented; no real Locked-OOS calibration artifact is approved. |
| Portfolio | `BLOCKED_BY_VALIDATION` | Exact-fingerprint approval injection works; no real portfolio Locked-OOS approval artifact exists. |
| Risk | `FIXTURE_TESTED` | Causal correlation baseline, size validation, covariance, concentration, liquidity and fail-closed rules pass deterministic contracts. |
| Stress | `FIXTURE_TESTED` | Governed stress is in the daily risk chain; production veto authority requires an exact approved risk artifact. |
| Backtest | `BLOCKED_BY_DATA` | One PIT-gated engine exists, but certified survivorship-safe historical evidence remains unavailable. |
| Locked OOS | `BLOCKED_BY_DATA` | No real locked test was opened or promoted in this closure. |
| Terminal | `FIXTURE_TESTED` | Renderer identity is checked against the persisted DailyQuantResult from the vertical production path. |
| Manual Execution | `FIXTURE_TESTED` | Accepted recommendations support persisted multi-fill PENDING/PARTIAL/FILLED/CANCELLED/MODIFIED state; only actual fills mutate holdings. |
| Live Capital | `DISABLED` | LIVE_CAPITAL_NOT_APPROVED; real PIT, Locked-OOS, approval and shadow-forward evidence are incomplete. |

## Validation checkpoint

- Command: `pytest -q`
- Result: `PENDING_FINAL_PART2_REGRESSION`
- Quant critical: `31 passed at working-tree checkpoint`
- Commit under test: `fb035499d91da8e3f234e10890dd86ae5abbd0d8+PART2_WORKTREE`

`FIXTURE_TESTED` proves a deterministic code path only. It does not mean real-data
PIT certification, Locked-OOS validation, production approval, or live-capital
readiness.

Live capital remains disabled. Charles Schwab execution is manual and recorded only
after the user enters actual fills; no broker API or automatic order submission
exists.
