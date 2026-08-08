from personal_alpha_terminal.terminal.execution import (
    ExecutionFeasibilityEngine,
    ExecutionInputs,
    ExecutionStatus,
)
from personal_alpha_terminal.terminal.market_sessions import MarketSession
from personal_alpha_terminal.terminal.quality import DataSafetyStatus


def _inputs(**changes) -> ExecutionInputs:
    values = {
        "action": "BUY",
        "session": MarketSession.REGULAR,
        "data_safety": DataSafetyStatus.SAFE,
        "price": 100.0,
        "spread_rate": 0.001,
        "average_daily_dollar_volume": 100_000_000.0,
        "order_value": 10_000.0,
        "annualized_volatility": 0.25,
        "estimated_slippage_rate": 0.0005,
        "portfolio_exposure_after": 0.9,
    }
    values.update(changes)
    return ExecutionInputs(**values)


def test_regular_liquid_limit_first_plan_is_executable() -> None:
    result = ExecutionFeasibilityEngine().assess(_inputs())
    assert result.status is ExecutionStatus.EXECUTABLE
    assert result.recommended_order_type == "LIMIT_FIRST"


def test_degraded_data_blocks_buy() -> None:
    result = ExecutionFeasibilityEngine().assess(
        _inputs(data_safety=DataSafetyStatus.DEGRADED)
    )
    assert result.status is ExecutionStatus.BLOCKED


def test_night_is_information_only() -> None:
    result = ExecutionFeasibilityEngine().assess(_inputs(session=MarketSession.NIGHT))
    assert result.status is ExecutionStatus.WAIT
    assert any("information-only" in reason for reason in result.reasons)


def test_missing_liquidity_never_assumes_zero_cost() -> None:
    result = ExecutionFeasibilityEngine().assess(
        _inputs(average_daily_dollar_volume=None, spread_rate=None)
    )
    assert result.status is not ExecutionStatus.EXECUTABLE
    assert result.estimated_cost_rate is None
