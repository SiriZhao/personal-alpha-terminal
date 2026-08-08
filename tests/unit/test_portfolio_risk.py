from datetime import date

import pytest

from personal_alpha_terminal.dashboard.schemas import PortfolioOption
from personal_alpha_terminal.portfolio.risk import calculate_portfolio_risk


def test_portfolio_risk_calculates_metrics_and_cash_exposure() -> None:
    portfolio = PortfolioOption(id=1, name="Core", base_currency="USD")
    histories = {
        1: (
            (date(2026, 7, 1), 100.0),
            (date(2026, 7, 2), 102.0),
            (date(2026, 7, 3), 101.0),
            (date(2026, 7, 4), 104.0),
        ),
        2: (
            (date(2026, 7, 1), 50.0),
            (date(2026, 7, 2), 49.0),
            (date(2026, 7, 3), 51.0),
            (date(2026, 7, 4), 52.0),
        ),
    }

    result = calculate_portfolio_risk(
        portfolio=portfolio,
        weights={1: 0.5, 2: 0.3},
        histories=histories,
        markets={1: "US", 2: "US"},
        industries={1: "Technology", 2: "Healthcare"},
        annual_risk_free_rate=0,
    )

    assert result.available
    assert result.metrics is not None
    assert result.metrics.observations == 3
    assert result.metrics.annualized_volatility > 0
    assert result.metrics.top_position_weight == 0.625
    assert result.market_exposure[-1].name == "现金"
    assert result.market_exposure[-1].weight == pytest.approx(0.2)
    assert len(result.equity_curve) == 3


def test_portfolio_risk_rejects_insufficient_history() -> None:
    portfolio = PortfolioOption(id=1, name="Core", base_currency="USD")

    result = calculate_portfolio_risk(
        portfolio=portfolio,
        weights={1: 1.0},
        histories={1: ((date(2026, 7, 1), 100.0),)},
        markets={1: "US"},
        industries={1: "Technology"},
        annual_risk_free_rate=0,
    )

    assert not result.available
    assert "历史价格" in (result.reason or "")
