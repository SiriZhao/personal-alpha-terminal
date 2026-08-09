# Current Status

Status as of 2026-08-09. This document supersedes historical release, paper-trading,
Streamlit, and production-readiness claims elsewhere under `docs/reports/`.

| Capability | Current evidence state |
|---|---|
| US runtime/database isolation | IMPLEMENTED_FIXTURE_TESTED |
| Layered US gates | IMPLEMENTED_FIXTURE_TESTED |
| USAdaptiveAlphaCoreV1 executable object | IMPLEMENTED_FIXTURE_TESTED |
| Headless daily Alpha -> portfolio -> decision | IMPLEMENTED_FIXTURE_TESTED |
| PIT universe/corporate actions/total return | BLOCKED_BY_DATA |
| Quality/value PIT fundamentals | BLOCKED_BY_DATA |
| Locked OOS Alpha evidence | BLOCKED_BY_DATA |
| Live display data | REAL_DATA_TESTED, not PIT-certified |
| Action generation | BLOCKED_BY_DATA |
| Shadow Forward with executable candidates | BLOCKED_BY_DATA |
| Small-capital Manual Pilot | DISABLED |
| Manual execution audit (no automatic holdings mutation) | IMPLEMENTED_FIXTURE_TESTED |
| EffectiveRuntimeConfig / deterministic fingerprints | IMPLEMENTED_FIXTURE_TESTED |
| Sequential stage evidence hash chain | IMPLEMENTED_FIXTURE_TESTED |
| Portfolio validation-artifact injection path | IMPLEMENTED_FIXTURE_TESTED |
| Real Locked-OOS portfolio approval artifact | BLOCKED_BY_DATA |
| Probability calibration artifact contract | IMPLEMENTED_FIXTURE_TESTED |
| Real Locked-OOS probability calibration | BLOCKED_BY_DATA |
| Immutable section CLI (`--run-id`) | IMPLEMENTED_FIXTURE_TESTED |

Current Alembic head: `c3f4a5b6d7e8`.

There is no known permanent code path that prevents an exact, independently produced
portfolio-validation or probability-calibration artifact from being consumed. No such real
Locked-OOS artifact is currently present, so Portfolio/Action remains blocked even if data
certification later passes.

No current result guarantees principal preservation or future outperformance.
