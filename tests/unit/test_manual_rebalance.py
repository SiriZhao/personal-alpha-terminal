from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from personal_alpha_terminal.research import (
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)
from personal_alpha_terminal.us_quant.manual_rebalance import (
    ManualFill,
    ManualRebalanceEngine,
    RebalanceCandidate,
)


def _authorization():
    request = ResearchDataRequest(
        ResearchPurpose.REBALANCE,
        "US",
        "stock",
        date(2020, 1, 1),
        date(2026, 7, 31),
        datetime(2026, 8, 1, 0, tzinfo=UTC),
        "point_in_time_total_return",
        "snapshot-1",
    )
    evidence = ResearchDataEvidence(
        "US",
        "stock",
        "passed",
        "primary",
        "adapter",
        ("source-1", "source-2"),
        datetime(2026, 7, 31, 23, tzinfo=UTC),
        "certified",
        "point_in_time_total_return",
        "snapshot-1",
        datetime(2026, 7, 31, 22, tzinfo=UTC),
        True,
        True,
        0.0,
        0.0,
        0.01,
        0.005,
        "data-v1",
        True,
        True,
        True,
        True,
    )
    return ResearchDataGate().authorize(
        request, evidence, evaluated_at=datetime(2026, 8, 1, 0, tzinfo=UTC)
    )


def _candidate() -> RebalanceCandidate:
    return RebalanceCandidate(
        ticker="AAPL",
        permanent_security_id="US-FIGI-AAPL",
        current_weight=0.0,
        target_weight=0.10,
        reference_price=100.0,
        lot_size=1,
        maximum_shares=100,
        evidence_grade="OOS Evidence",
        base_signal="quality-constrained momentum",
        conditional_overlay="neutral",
        risk_adjustment="single-name cap applied",
        estimated_cost_rate=0.001,
        liquidity="within ADV limit",
        earnings_risk="no certified event within window",
        invalidation_condition="trend and evidence decay",
        order_deadline=datetime(2026, 8, 2, 20, tzinfo=UTC),
    )


def test_ticket_respects_cash_rounding_and_is_never_automatic() -> None:
    ticket = ManualRebalanceEngine().generate(
        authorization=_authorization(),
        candidates=(_candidate(),),
        portfolio_value=10_000,
        available_cash=500,
        signal_as_of=datetime(2026, 7, 31, 22, tzinfo=UTC),
        order_generation_time=datetime(2026, 8, 1, 1, tzinfo=UTC),
        earliest_execution_time=datetime(2026, 8, 3, 14, 31, tzinfo=UTC),
        maximum_turnover=0.20,
    )
    assert ticket.items[0].suggested_shares == 4
    assert ticket.manual_review_required
    assert not ticket.automatic_execution_allowed


def test_blocked_authorization_cannot_generate_ticket() -> None:
    authorization = _authorization()
    bad = replace(
        authorization,
        request=replace(authorization.request, purpose=ResearchPurpose.RESEARCH),
    )
    with pytest.raises(Exception, match="ResearchDataGate"):
        ManualRebalanceEngine().generate(
            authorization=bad,
            candidates=(_candidate(),),
            portfolio_value=10_000,
            available_cash=10_000,
            signal_as_of=datetime(2026, 7, 31, 22, tzinfo=UTC),
            order_generation_time=datetime(2026, 8, 1, 1, tzinfo=UTC),
            earliest_execution_time=datetime(2026, 8, 3, 14, 31, tzinfo=UTC),
            maximum_turnover=0.20,
        )


def test_fill_attribution_reports_slippage_fees_and_partial_fill() -> None:
    engine = ManualRebalanceEngine()
    ticket = engine.generate(
        authorization=_authorization(),
        candidates=(_candidate(),),
        portfolio_value=10_000,
        available_cash=10_000,
        signal_as_of=datetime(2026, 7, 31, 22, tzinfo=UTC),
        order_generation_time=datetime(2026, 8, 1, 1, tzinfo=UTC),
        earliest_execution_time=datetime(2026, 8, 3, 14, 31, tzinfo=UTC),
        maximum_turnover=0.20,
    )
    attribution = engine.attribute_fill(
        ticket,
        ManualFill("US-FIGI-AAPL", 101.0, 5, 1.0, datetime(2026, 8, 3, 15, tzinfo=UTC)),
    )
    assert attribution.implementation_shortfall == pytest.approx(6.0)
    assert attribution.share_completion_rate == pytest.approx(0.5)
