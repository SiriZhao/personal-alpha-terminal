# Current Status

Generated from `docs/CURRENT_STATUS.json` at `2026-08-15T16:50:53.880726Z`.
This file supersedes historical release/readiness claims under `docs/reports/`.

- Version: `1.2.0-rc.1`
- Git commit: `7dce2e5418803d73d26da86ea2a4171ed9dd94e4`
- Build ID: `pat-1.2.0-rc.1-7dce2e541880-20260815`
- Evidence level: `VALID_ANALYSIS_ACTIONABLE_PROVISIONAL`
- Operating mode: `MANUAL_ADVISORY_ONLY`
- Alembic head: `d4a5b6c7d8e9`

| Capability | Evidence state | Current evidence |
|---|---|---|
| AI Intelligence | `REAL_DATA_TESTED` | AI_BRIEF status PASS; AI trade authority NONE; production influence NONE. |
| Alpha | `REAL_DATA_TESTED` | USAdaptiveAlphaCoreV1 produced 2,135 cross-sectional factor rows; 1,171 candidates reached the optimizer. |
| Backtest | `BLOCKED_BY_DATA` | No survivorship-safe historical certification. |
| DATA | `REAL_DATA_TESTED` | acceptance run daily-2420c68452d142298e6b42482341391f; DATA PASS; PIT cutoff 2026-08-14T20:30:00+00:00; 2,135 universe members. |
| ETF Research | `REAL_DATA_TESTED` | ETF sleeve remains RESEARCH_CANDIDATE; no formal ETF recommendations in ROUND27 acceptance. |
| Live Capital | `DISABLED` | LIVE_CAPITAL_NOT_APPROVED |
| Locked OOS | `BLOCKED_BY_DATA` | No mature OOS sample for probability promotion. |
| Manual Execution | `FIXTURE_TESTED` | Manual execution remains the only execution path. |
| Market Regime | `OBSERVATION_ONLY` | deterministic market-regime-v1 runs in OBSERVATION_ONLY; no production influence. |
| PIT | `REAL_DATA_TESTED` | PIT stage PASS for the acceptance run; historical research certification remains NOT_CERTIFIABLE. |
| Portfolio | `REAL_DATA_TESTED` | optimizer input 1,171; no fixed cardinality cap; 10 non-zero targets produced by SLSQP constraints. |
| Portfolio Breadth | `BLOCKED_BY_DATA` | Fixture/OOS-style breadth research only; no certified historical OOS or mature forward outcome evidence. |
| Probability | `BLOCKED_BY_VALIDATION` | RESEARCH_ONLY; matured outcomes 0; effective N 0; production influence 0%. |
| Risk | `REAL_DATA_TESTED` | RISK PASS; expected vol 7.60%; gross 27.23%; cash 72.77%; size neutralization degraded. |
| Stress | `FIXTURE_TESTED` | Governed stress remains in the risk chain. |
| Terminal | `REAL_DATA_TESTED` | backend formal actions and renderer action list are cardinality/ticker consistent for the acceptance run. |

## Validation checkpoint

- Command: `None`
- Result: `None`
- Quant critical: `31 passed`
- Commit under test: `None`

`FIXTURE_TESTED` proves a deterministic code path only. It does not mean real-data
PIT certification, Locked-OOS validation, production approval, or live-capital
readiness.

Live capital remains disabled. Charles Schwab execution is manual and recorded only
after the user enters actual fills; no broker API or automatic order submission
exists.
