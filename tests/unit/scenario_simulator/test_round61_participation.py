from __future__ import annotations

import pytest

from personal_alpha_terminal.scenario_simulator.flagship_stress import (
    DEFAULT_SEED,
    EVALUATION_SESSIONS,
    SCENARIOS,
)
from personal_alpha_terminal.scenario_simulator.round61_participation import (
    POLICIES,
    _simulate_scenario,
)


@pytest.fixture(scope="module")
def normal_market():
    spec = next(item for item in SCENARIOS if item.name == "NORMAL_MIXED_MARKET")
    return _simulate_scenario(spec, seed=DEFAULT_SEED)


def test_round61_runs_all_required_counterfactuals_without_future_data(normal_market) -> None:
    assert {item.policy for item in normal_market.policies} == set(POLICIES)
    assert len(normal_market.steps) == EVALUATION_SESSIONS
    assert normal_market.blocked_count == 0
    assert normal_market.primary_count + normal_market.recovery_count == 5


def test_round61_active_return_reconciles_with_machine_precision(normal_market) -> None:
    for step in normal_market.steps:
        active = step.portfolio_return - step.benchmark_return
        reconciled = (
            step.stock_selection_return
            + step.sector_allocation_return
            + step.exposure_drag
            + step.transaction_cost_drag
            + step.residual_return
        )
        assert active == pytest.approx(reconciled, abs=1e-12)
    assert abs(normal_market.residual) <= 1e-12


def test_round61_reports_market_participation_and_cost_diagnostics(normal_market) -> None:
    for metrics in normal_market.policies:
        assert 0 <= metrics.mean_gross <= 1
        assert 0 <= metrics.mean_cash <= 1
        assert metrics.turnover_l1 >= 0
    current = next(
        item for item in normal_market.policies if item.policy == "A_CURRENT_PRODUCTION"
    )
    assert current.upside_capture is not None
    assert current.downside_capture is not None
    assert current.participation_gap is not None
