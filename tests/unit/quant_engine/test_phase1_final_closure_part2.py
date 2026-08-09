from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from personal_alpha_terminal.quant_engine.factors.cross_sectional import (
    FactorSignalStatus,
    FactorSpec,
    process_cross_section,
)
from personal_alpha_terminal.quant_engine.input_assembler import (
    ProductionDailyQuantInputAssembler,
)
from personal_alpha_terminal.quant_engine.risk.budget import (
    CorrelationRiskStatus,
    DynamicRiskBudget,
)
from personal_alpha_terminal.quant_engine.risk.model import (
    AssetRiskMetadata,
    PortfolioRiskModel,
    SizeExposureStatus,
)
from personal_alpha_terminal.quant_engine.risk.stress import (
    StressRiskConfig,
    StressStatus,
    evaluate_portfolio_stress,
)
from personal_alpha_terminal.terminal.market_sessions import (
    CalendarUnavailableError,
    MarketSessionCalendar,
)

pytestmark = pytest.mark.quant_critical


def _correlation_history(*, spike: bool, sessions: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(1207)
    first = rng.normal(0, 0.01, sessions)
    second = rng.normal(0, 0.01, sessions)
    if spike:
        common = rng.normal(0, 0.015, 63)
        first[-63:] = common + rng.normal(0, 0.0005, 63)
        second[-63:] = common + rng.normal(0, 0.0005, 63)
    index = pd.date_range("2024-01-02", periods=sessions, freq="B", tz="UTC")
    return pd.DataFrame({"A": first, "B": second}, index=index)


def _risk_state(*, spike: bool, sessions: int = 400):
    returns = _correlation_history(spike=spike, sessions=sessions)
    benchmark = returns.mean(axis=1) + 0.0001
    cutoff = returns.index[-1].to_pydatetime() + timedelta(hours=1)
    return ProductionDailyQuantInputAssembler._risk_state(
        returns,
        benchmark,
        {"A": 0.4, "B": 0.4},
        decision_cutoff=cutoff,
    )


def test_causal_correlation_baseline_is_strictly_earlier_and_spike_triggers() -> None:
    normal = _risk_state(spike=False)
    spike = _risk_state(spike=True)

    assert normal.correlation_status is CorrelationRiskStatus.VALID
    assert spike.correlation_status is CorrelationRiskStatus.VALID
    assert spike.correlation_baseline_samples == 252
    assert spike.correlation_recent_samples == 63
    assert spike.correlation_jump is not None and spike.correlation_jump > 0.75
    budget = DynamicRiskBudget().evaluate(
        regime=None,
        state=spike,
        configured_target_volatility=0.20,
    )
    assert "correlation spike reduced diversification capacity" in budget.reasons
    assert budget.gross_exposure_multiplier < 1


def test_correlation_insufficient_history_is_not_fabricated_as_zero() -> None:
    state = _risk_state(spike=False, sessions=180)

    assert state.correlation_status is CorrelationRiskStatus.NOT_VALIDATED
    assert state.correlation_jump is None
    assert state.average_correlation is None
    assert state.baseline_average_correlation is None
    assert not DynamicRiskBudget().evaluate(
        regime=None,
        state=state,
        configured_target_volatility=0.20,
    ).allow_new_risk


def test_correlation_risk_rejects_future_observations() -> None:
    returns = _correlation_history(spike=True)
    with pytest.raises(ValueError, match="future observations"):
        ProductionDailyQuantInputAssembler._risk_state(
            returns,
            returns.mean(axis=1),
            {"A": 0.4, "B": 0.4},
            decision_cutoff=returns.index[-2].to_pydatetime(),
        )


def test_size_exposure_is_not_validated_without_pit_market_cap() -> None:
    returns = _correlation_history(spike=False, sessions=100)
    metadata = (
        AssetRiskMetadata("A", "Technology", 20_000_000, None),
        AssetRiskMetadata("B", "Healthcare", 20_000_000, None),
    )
    risk = PortfolioRiskModel().fit(
        returns,
        metadata=metadata,
        benchmark_returns=returns.mean(axis=1),
    )

    assert risk.size_scores == {}
    assert risk.size_exposure_status is SizeExposureStatus.NOT_VALIDATED


def test_neutralization_reports_insufficient_sector_group_and_dof() -> None:
    now = datetime(2026, 8, 7, 21, tzinfo=UTC)
    observations = pd.DataFrame(
        {
            "permanent_security_id": ["A", "B", "C", "D", "E"],
            "available_at": [now - timedelta(hours=1)] * 5,
            "quality": [1, 2, 3, 4, 5],
            "sector": ["Technology", "Technology", "Healthcare", "Healthcare", "Solo"],
            "market_cap": [10, 20, 30, 40, 50],
        }
    )
    result = process_cross_section(
        observations,
        (FactorSpec("quality", minimum_observations=5),),
        as_of=now,
        minimum_required_factors=1,
    )
    evidence = result.neutralization["quality"]

    assert result.statuses["quality"] is FactorSignalStatus.NOT_VALIDATED
    assert evidence.status is FactorSignalStatus.NOT_VALIDATED
    assert evidence.insufficient_groups == ("Solo",)
    assert evidence.group_count == 3
    assert evidence.minimum_group_size == 2
    assert evidence.degrees_of_freedom >= 0
    assert pd.isna(
        result.frame.loc[
            result.frame["permanent_security_id"] == "E", "quality__normalized"
        ].iloc[0]
    )


def test_stress_requires_governed_validation_and_can_veto() -> None:
    returns = _correlation_history(spike=False, sessions=100)
    metadata = (
        AssetRiskMetadata("A", "Technology", 20_000_000, -0.5),
        AssetRiskMetadata("B", "Healthcare", 20_000_000, 0.5),
    )
    risk = PortfolioRiskModel().fit(
        returns,
        metadata=metadata,
        benchmark_returns=returns.mean(axis=1),
    )
    unvalidated = evaluate_portfolio_stress(
        weights={"A": 0.4, "B": 0.4},
        portfolio_returns=tuple(returns.mean(axis=1)),
        risk=risk,
        portfolio_value=100_000,
        maximum_adv_participation=0.02,
    )
    veto = evaluate_portfolio_stress(
        weights={"A": 0.4, "B": 0.4},
        portfolio_returns=tuple(returns.mean(axis=1)),
        risk=risk,
        portfolio_value=100_000,
        maximum_adv_participation=0.02,
        config=StressRiskConfig(
            production_validated=True,
            validation_id="stress-validation-test",
            maximum_single_name_loss=0.01,
        ),
    )

    assert unvalidated.status is StressStatus.NOT_VALIDATED
    assert veto.status is StressStatus.BLOCKED
    assert "single_name_shock_loss" in veto.hard_failures


def test_production_calendar_fails_closed_and_dev_fallback_is_explicit(monkeypatch) -> None:
    def unavailable(_name: str) -> object:
        raise ImportError("calendar fixture unavailable")

    monkeypatch.setattr(
        "personal_alpha_terminal.terminal.market_sessions.importlib.import_module",
        unavailable,
    )
    production = MarketSessionCalendar()
    with pytest.raises(CalendarUnavailableError, match="certified XNYS"):
        production.is_trading_day(datetime(2026, 8, 10, tzinfo=UTC).date())

    development = MarketSessionCalendar(allow_deterministic_fallback=True)
    assert development.is_trading_day(datetime(2026, 8, 10, tzinfo=UTC).date())
