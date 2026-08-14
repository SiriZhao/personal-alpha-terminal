"""ROUND25 PHASE 7: pre-execution overnight risk check tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from personal_alpha_terminal.application.pre_execution import (
    CHECK_FAIL,
    CHECK_PASS,
    CHECK_UNAVAILABLE,
    PRE_EXECUTION_CLEAR,
    PRE_EXECUTION_DATA_LIMITED,
    PRE_EXECUTION_REVIEW_REQUIRED,
    PreExecutionCheck,
    build_assessment,
    check_halts_and_corporate_events,
    check_market_gap,
    check_stale_market_data,
)

AS_OF = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
NOW = datetime(2026, 8, 14, 13, 0, tzinfo=UTC)


def test_clean_checks_produce_clear_status() -> None:
    assessment = build_assessment(
        decision_as_of=AS_OF,
        now=NOW,
        checks=(
            PreExecutionCheck("market_gap", CHECK_PASS, "ok"),
            PreExecutionCheck("market_data_freshness", CHECK_PASS, "ok"),
        ),
    )
    assert assessment.status == PRE_EXECUTION_CLEAR
    assert assessment.manual_review_required is False


def test_severe_gap_requires_human_review() -> None:
    check = check_market_gap(decision_close=100.0, latest_close=94.0)
    assert check.status == CHECK_FAIL
    assessment = build_assessment(
        decision_as_of=AS_OF, now=NOW, checks=(check,)
    )
    assert assessment.status == PRE_EXECUTION_REVIEW_REQUIRED
    assert assessment.manual_review_required is True
    # The layer never cancels by itself.
    assert assessment.document()["auto_cancel"] is False
    assert assessment.document()["alpha_recomputation"] is False


def test_missing_gap_evidence_is_limited_not_clear() -> None:
    check = check_market_gap(decision_close=None, latest_close=110.0)
    assert check.status == CHECK_UNAVAILABLE
    assessment = build_assessment(
        decision_as_of=AS_OF, now=NOW, checks=(check,)
    )
    assert assessment.status == PRE_EXECUTION_DATA_LIMITED


def test_stale_market_data_requires_review() -> None:
    check = check_stale_market_data(
        latest_available_at=AS_OF - timedelta(days=1),
        decision_as_of=AS_OF,
        now=NOW,
    )
    assert check.status == CHECK_FAIL


def test_fresh_market_data_passes() -> None:
    check = check_stale_market_data(
        latest_available_at=AS_OF + timedelta(hours=1),
        decision_as_of=AS_OF,
        now=NOW,
    )
    assert check.status == CHECK_PASS


def test_halted_symbol_requires_review() -> None:
    check = check_halts_and_corporate_events(halted_symbols=frozenset({"VSTS"}))
    assert check.status == CHECK_FAIL


def test_no_events_passes() -> None:
    check = check_halts_and_corporate_events()
    assert check.status == CHECK_PASS
