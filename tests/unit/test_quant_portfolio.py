from datetime import UTC, date, datetime, timedelta

import pytest

from personal_alpha_terminal.quant_engine.portfolio.allocation import AllocationEngine
from personal_alpha_terminal.quant_engine.portfolio.holdings import Holding, PortfolioSnapshot
from personal_alpha_terminal.quant_engine.portfolio.rebalance import RebalanceEngine
from personal_alpha_terminal.quant_engine.risk.position_control import PositionConstraints
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)


def _authorization(purpose: ResearchPurpose) -> ResearchDataAuthorization:
    now = datetime(2026, 1, 10, tzinfo=UTC)
    request = ResearchDataRequest(
        purpose,
        "US",
        "stock",
        date(2025, 1, 1),
        date(2026, 1, 9),
        now,
        "point_in_time_total_return",
        "pit-us",
        timedelta(days=10),
    )
    evidence = ResearchDataEvidence(
        "US", "stock", "passed", "fixture", "fixture", ("source-a", "source-b"),
        now - timedelta(days=1), "certified", "point_in_time_total_return", "pit-us",
        now - timedelta(days=10), True, True, 0, 0, 0.01, 0.01, "v1", True, True,
        True, True,
    )
    return ResearchDataGate().authorize(request, evidence, evaluated_at=now)


def test_allocation_respects_position_cash_and_sector_constraints() -> None:
    result = AllocationEngine().allocate(
        authorization=_authorization(ResearchPurpose.PORTFOLIO_DECISION),
        selected_scores={"A": 90, "B": 80, "C": 70},
        annualized_volatility={"A": 0.2, "B": 0.25, "C": 0.3},
        sectors={"A": "Technology", "B": "Health", "C": "Finance"},
        constraints=PositionConstraints(
            maximum_single_position=0.3,
            maximum_sector_weight=0.35,
            minimum_cash_weight=0.1,
            maximum_gross_exposure=0.9,
        ),
    )

    assert max(result.target_weights.values()) <= 0.3
    assert result.cash_weight == pytest.approx(0.1)


def test_rebalance_plan_is_manual_and_includes_costs() -> None:
    snapshot = PortfolioSnapshot(
        datetime(2026, 1, 9, tzinfo=UTC),
        (Holding("US-A", "A", 10, 90, 100, "Technology"),),
        1_000,
    )
    plan = RebalanceEngine().generate_plan(
        authorization=_authorization(ResearchPurpose.REBALANCE),
        snapshot=snapshot,
        target_weights={"US-A": 0.25},
        reference_prices={"US-A": 100},
        ticker_by_id={"US-A": "A"},
        generated_at=datetime(2026, 1, 10, tzinfo=UTC),
    )

    assert plan.execution_status == "NOT_EXECUTED"
    assert plan.tickets[0].requires_manual_confirmation
    assert plan.tickets[0].estimated_cost > 0


def test_rebalance_requires_approved_gate() -> None:
    research_authorization = _authorization(ResearchPurpose.PORTFOLIO_DECISION)
    snapshot = PortfolioSnapshot(datetime(2026, 1, 9, tzinfo=UTC), (), 1_000)
    with pytest.raises(Exception, match="ResearchDataGate"):
        RebalanceEngine().generate_plan(
            authorization=research_authorization,
            snapshot=snapshot,
            target_weights={"US-A": 0.1},
            reference_prices={"US-A": 100},
            ticker_by_id={"US-A": "A"},
            generated_at=datetime(2026, 1, 10, tzinfo=UTC),
        )
