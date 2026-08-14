"""ROUND25 PHASE 1: FORMAL / RESEARCH / CONTEXT semantic domain isolation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from personal_alpha_terminal.application.semantic_domains import (
    CONTEXT_ONLY,
    FORMAL_ACTIONABLE,
    RESEARCH_CANDIDATE,
    annotate_domain,
    classify_item,
    formal_action_rows,
    formal_required_fields_present,
    is_finite_metric,
    is_no_action,
    research_candidate_rows,
)


def _formal_stock(symbol: str = "VSTS") -> dict[str, object]:
    return {
        "symbol": symbol,
        "action": "BUY",
        "current_weight": 0.0,
        "target_weight": 0.07,
        "delta_weight": 0.07,
        "estimated_value": 6943.57,
        "estimated_quantity": 513,
        "estimated_cost": 3.95,
        "earliest_execution_time": datetime(2026, 8, 14, 13, 30, tzinfo=UTC),
    }


def _etf_candidate(symbol: str = "VOO") -> dict[str, object]:
    return {
        "symbol": symbol,
        "instrument_type": "ETF",
        "sleeve": "ETF_CORE",
        "target_weight": 0.0707,
        "current_weight": 0.0,
        "delta_weight": 0.0707,
        "eligibility": [],
        "eligible": True,
        "momentum_vol_ratio": 1.2544,
        "momentum_252_21": 0.5123,
        "annualized_volatility": 0.408,
        "model_status": "RESEARCH_CANDIDATE",
        "model_version": "etf-sleeves-v1",
        "domain": RESEARCH_CANDIDATE,
        "trading_permission": "NONE",
        "not_part_of_execution_plan": True,
    }


def test_formal_stock_row_is_formal_actionable() -> None:
    assert classify_item(_formal_stock()) == FORMAL_ACTIONABLE


def test_etf_research_candidate_is_never_formal() -> None:
    assert classify_item(_etf_candidate()) == RESEARCH_CANDIDATE


def test_context_benchmark_is_context_only() -> None:
    benchmark = {"symbol": "SPY", "period_return": 0.28, "annualized_volatility": 0.17}
    assert classify_item(benchmark) == CONTEXT_ONLY


def test_no_action_row_is_not_formal() -> None:
    row = _formal_stock()
    row["action"] = "NO_ACTION"
    assert is_no_action("NO_ACTION")
    assert classify_item(row) != FORMAL_ACTIONABLE


def test_formal_rows_missing_fields_are_excluded() -> None:
    incomplete = {"symbol": "AAPL", "action": "BUY", "current_weight": 0.0}
    rows = formal_action_rows([_formal_stock(), incomplete, _etf_candidate()])
    assert [row["symbol"] for row in rows] == ["VSTS"]


def test_formal_required_fields_present_rejects_missing_and_none() -> None:
    assert formal_required_fields_present(_formal_stock())
    missing = _formal_stock()
    del missing["estimated_quantity"]
    assert not formal_required_fields_present(missing)
    none_value = _formal_stock()
    none_value["earliest_execution_time"] = None
    assert not formal_required_fields_present(none_value)


def test_research_candidate_rows_isolate_etf_targets() -> None:
    rows = research_candidate_rows(
        [_formal_stock(), _etf_candidate("VOO"), _etf_candidate("IVV")]
    )
    assert {row["symbol"] for row in rows} == {"VOO", "IVV"}


def test_annotate_domain_stamps_explicit_domain() -> None:
    annotated = annotate_domain([{"symbol": "SPY"}], CONTEXT_ONLY)
    assert annotated[0]["domain"] == CONTEXT_ONLY


def test_is_finite_metric_rejects_nan_inf_strings() -> None:
    assert is_finite_metric(1.25)
    assert is_finite_metric(-0.03)
    assert not is_finite_metric(float("nan"))
    assert not is_finite_metric(float("inf"))
    assert not is_finite_metric(None)
    assert not is_finite_metric("1.25")


def test_dataclass_rows_are_supported() -> None:
    @dataclass(frozen=True)
    class FormalRow:
        symbol: str
        action: str
        current_weight: float
        target_weight: float
        delta_weight: float
        estimated_value: float
        estimated_quantity: int
        estimated_cost: float
        earliest_execution_time: datetime

    row = FormalRow(
        symbol="ATEX",
        action="BUY",
        current_weight=0.0,
        target_weight=0.028,
        delta_weight=0.028,
        estimated_value=2833.4,
        estimated_quantity=30,
        estimated_cost=1.58,
        earliest_execution_time=datetime(2026, 8, 14, 13, 30, tzinfo=UTC),
    )
    assert classify_item(row) == FORMAL_ACTIONABLE
