from datetime import date

import pytest

from personal_alpha_terminal.backtest.metrics import calculate_metrics
from personal_alpha_terminal.backtest.report import (
    render_strategy_report,
    visualization_payload,
)
from personal_alpha_terminal.backtest.schemas import (
    BacktestConfig,
    BacktestResult,
    DailyPortfolioPoint,
    HoldingPeriodResult,
    RebalanceRecord,
)


def _result() -> tuple[BacktestResult, BacktestConfig]:
    points = (
        DailyPortfolioPoint(date(2024, 1, 2), 100, 0, 0, 1, 0),
        DailyPortfolioPoint(date(2024, 1, 3), 110, 0.10, 0, 1, 0),
        DailyPortfolioPoint(date(2024, 1, 4), 99, -0.10, -0.10, 1, 0),
    )
    rebalances = (
        RebalanceRecord(
            signal_date=date(2024, 1, 2),
            execution_date=date(2024, 1, 3),
            status="executed",
            turnover=1,
            transaction_cost=1,
            nav_before=100,
            nav_after=99,
            target_weights={1: 1},
            rationale=("test",),
        ),
    )
    periods = (
        HoldingPeriodResult(date(2024, 1, 2), date(2024, 1, 3), 0.10),
        HoldingPeriodResult(date(2024, 1, 3), date(2024, 1, 4), -0.10),
    )
    metrics = calculate_metrics(
        points,
        rebalances,
        periods,
        initial_capital=100,
        annual_risk_free_rate=0,
    )
    result = BacktestResult(
        run_id=1,
        strategy_name="factor_quantile:roe",
        strategy_parameters={"type": "factor_quantile", "factor_name": "roe"},
        market="US",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 4),
        data_fingerprint="a" * 64,
        points=points,
        rebalances=rebalances,
        holding_periods=periods,
        metrics=metrics,
    )
    config = BacktestConfig(
        start_date=result.start_date,
        end_date=result.end_date,
        initial_capital=100,
        minimum_sessions=2,
    )
    return result, config


def test_metrics_use_geometric_return_drawdown_and_period_grain() -> None:
    result, _ = _result()

    assert result.metrics.total_return == pytest.approx(-0.01)
    assert result.metrics.maximum_drawdown == pytest.approx(-0.10)
    assert result.metrics.period_win_rate == pytest.approx(0.5)
    assert result.metrics.period_profit_loss_ratio == pytest.approx(1.0)
    assert result.metrics.total_turnover == pytest.approx(1.0)


def test_win_rate_includes_breakeven_and_excludes_unclosed_period() -> None:
    result, _ = _result()
    periods = (
        HoldingPeriodResult(date(2024, 1, 2), date(2024, 1, 3), 0.10),
        HoldingPeriodResult(date(2024, 1, 3), date(2024, 1, 4), 0.0),
        HoldingPeriodResult(
            date(2024, 1, 4),
            date(2024, 1, 5),
            10.0,
            is_closed=False,
        ),
    )

    metrics = calculate_metrics(
        result.points,
        result.rebalances,
        periods,
        initial_capital=100,
        annual_risk_free_rate=0,
    )

    assert metrics.period_win_rate == pytest.approx(0.5)
    assert metrics.period_profit_loss_ratio is None


def test_report_and_visualization_expose_required_outputs_and_limits() -> None:
    result, config = _result()
    report = render_strategy_report(
        result,
        config,
        data_sources=("synthetic:audited_fixture",),
    )
    payload = visualization_payload(result)

    assert report.report_type == "strategy_backtest"
    assert "## Observed Strengths" in report.markdown
    assert "## Applicable Conditions" in report.markdown
    assert "## Risks and Failure Conditions" in report.markdown
    assert "next available portfolio-calendar session open" in report.markdown
    assert "not a success probability" in report.markdown
    assert len(payload["equity_curve"]) == 3
    assert len(payload["drawdown_curve"]) == 3
    assert payload["annual_returns"][0]["year"] == 2024
