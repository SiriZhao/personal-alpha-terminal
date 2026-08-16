from __future__ import annotations

from personal_alpha_terminal.application.round36_audit import (
    build_round36_policy_recommendation,
)


def test_round36_policy_remains_retained_and_requires_human_approval() -> None:
    result = build_round36_policy_recommendation()
    assert result["recommendation"] == "CURRENT_POLICY_RETAINED"
    assert result["manual_approval_required"] is True
