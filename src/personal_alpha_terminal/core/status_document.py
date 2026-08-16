from __future__ import annotations

from collections.abc import Mapping

_ALLOWED_STATES = {
    "IMPLEMENTED",
    "FIXTURE_TESTED",
    "REAL_DATA_TESTED",
    "PIT_CERTIFIED",
    "LOCKED_OOS_VALIDATED",
    "PRODUCTION_APPROVED",
    "BLOCKED_BY_DATA",
    "BLOCKED_BY_VALIDATION",
    "NOT_VALIDATED",
    "OBSERVATION_ONLY",
    "DISABLED",
}


def render_current_status(payload: Mapping[str, object]) -> str:
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, dict):
        raise ValueError("CURRENT_STATUS capabilities must be an object")
    lines = [
        "# Current Status",
        "",
        f"Generated from `docs/CURRENT_STATUS.json` at `{payload['generated_at']}`.",
        "This file supersedes historical release/readiness claims under `docs/reports/`.",
        "",
        f"- Version: `{payload['version']}`",
        f"- Git commit: `{payload['git_commit']}`",
        f"- Build ID: `{payload['build_id']}`",
        f"- Evidence level: `{payload['evidence_level']}`",
        f"- Operating mode: `{payload['operating_mode']}`",
        f"- Alembic head: `{payload['alembic_head']}`",
        "",
        "| Capability | Evidence state | Current evidence |",
        "|---|---|---|",
    ]
    for name, value in capabilities.items():
        if not isinstance(value, dict):
            raise ValueError(f"capability {name} must be an object")
        state = value.get("state")
        note = value.get("evidence")
        if state not in _ALLOWED_STATES:
            raise ValueError(f"capability {name} has invalid state {state}")
        lines.append(f"| {name} | `{state}` | {note} |")
    tests = payload.get("validation_checkpoint")
    if isinstance(tests, dict):
        lines.extend(
            (
                "",
                "## Validation checkpoint",
                "",
                f"- Command: `{tests.get('command')}`",
                f"- Result: `{tests.get('result')}`",
                f"- Quant critical: `{tests.get('quant_critical')}`",
                f"- Commit under test: `{tests.get('commit')}`",
            )
        )
    lines.extend(
        (
            "",
            "`FIXTURE_TESTED` proves a deterministic code path only. It does not mean real-data",
            "PIT certification, Locked-OOS validation, production approval, or live-capital",
            "readiness.",
            "",
            "Live capital remains disabled. Charles Schwab execution is manual and recorded only",
            "after the user enters actual fills; no broker API or automatic order submission",
            "exists.",
            "",
        )
    )
    return "\n".join(lines)
