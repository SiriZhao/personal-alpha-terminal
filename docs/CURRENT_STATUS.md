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

Current Alembic head: `b2e3f4a5c6d7`.

No current result guarantees principal preservation or future outperformance.
