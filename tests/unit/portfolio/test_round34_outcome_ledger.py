from __future__ import annotations

from datetime import UTC, date, datetime

from personal_alpha_terminal.portfolio.outcome_ledger import (
    PortfolioForwardOutcome,
    PortfolioOutcomeLedger,
    PortfolioOutcomeObservation,
)


def _observation(observation_id: str = "obs-1") -> PortfolioOutcomeObservation:
    return PortfolioOutcomeObservation(
        observation_id=observation_id,
        portfolio_id=1,
        decision_run_id="run-1",
        run_bundle_id="bundle-1",
        decision_time=datetime(2026, 8, 16, 20, 30, tzinfo=UTC),
        execution_session=date(2026, 8, 17),
        symbol="AAA",
        target_weight=0.05,
        pre_trade_weight=0.0,
        recommended_quantity=10,
        accepted_quantity=10,
        actual_fill_quantity=10,
        intended_price=100.0,
        actual_fill_price=100.5,
        commission=1.0,
        spread_estimate=0.5,
        realized_slippage=0.5,
        cash_before=1000.0,
        cash_after=0.0,
        position_before=0.0,
        position_after=10.0,
        nav_before=1000.0,
        nav_after=1005.0,
        benchmark_levels={"SPY": 500.0},
        created_at=datetime(2026, 8, 16, 21, 0, tzinfo=UTC),
        provenance_hash="prov-1",
    )


def test_ledger_is_append_only_and_duplicate_is_occurrence(tmp_path) -> None:
    ledger = PortfolioOutcomeLedger(tmp_path / "ledger")
    assert ledger.append_observation(_observation()) is True
    assert ledger.append_observation(_observation()) is False
    assert len(ledger.observations()) == 1
    assert len(ledger.occurrences_path.read_text(encoding="utf-8").splitlines()) == 2
    index = ledger.write_canonical_index()
    assert index["canonical_observation_rows"] == 1
    assert index["duplicate_observation_rows"] == 0


def test_forward_outcome_duplicate_and_maturity_guard(tmp_path) -> None:
    ledger = PortfolioOutcomeLedger(tmp_path / "ledger")
    ledger.append_observation(_observation())
    outcome = PortfolioForwardOutcome(
        outcome_id="outcome-1",
        observation_id="obs-1",
        maturity_sessions=21,
        created_at=datetime(2026, 8, 16, tzinfo=UTC),
        target_date=date(2026, 8, 17),
        maturity_date=date(2026, 9, 15),
        matured=True,
        realized_return=0.01,
        benchmark_return=0.005,
        excess_return=0.005,
        cost_adjusted_excess_return=0.004,
    )
    assert ledger.append_outcome(outcome) is True
    assert ledger.append_outcome(outcome) is False


def test_matured_outcome_requires_return(tmp_path) -> None:
    ledger = PortfolioOutcomeLedger(tmp_path / "ledger")
    ledger.append_observation(_observation())
    outcome = PortfolioForwardOutcome(
        outcome_id="bad",
        observation_id="obs-1",
        maturity_sessions=1,
        created_at=datetime(2026, 8, 16, tzinfo=UTC),
        target_date=date(2026, 8, 17),
        maturity_date=date(2026, 8, 18),
        matured=True,
        realized_return=None,
        benchmark_return=None,
        excess_return=None,
        cost_adjusted_excess_return=None,
    )
    try:
        ledger.append_outcome(outcome)
    except ValueError as error:
        assert "matured outcome" in str(error)
    else:
        raise AssertionError("matured outcome without return should fail")


def test_target_actual_fields_are_not_aliased() -> None:
    observation = _observation()
    assert observation.target_weight == 0.05
    assert observation.actual_fill_quantity == 10
    assert observation.target_weight != observation.actual_fill_quantity
