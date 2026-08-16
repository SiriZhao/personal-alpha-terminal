from __future__ import annotations

from personal_alpha_terminal.application.round38_audit import (
    build_round38_locked_oos,
)


def test_round38_locked_oos_remains_not_certifiable() -> None:
    result = build_round38_locked_oos()
    assert result["locked_oos_status"] == "NOT_CERTIFIABLE"
    assert result["reason"]
