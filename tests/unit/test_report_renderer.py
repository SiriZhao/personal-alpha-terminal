from datetime import date
from decimal import Decimal

import pytest

from personal_alpha_terminal.analysis.market_regime.schemas import (
    MarketRegimePoint,
    MarketRegimeResult,
    RegimeCalibrationReport,
)
from personal_alpha_terminal.dashboard.schemas import (
    InstrumentOption,
    MarketIndexSnapshot,
    PricePoint,
    StockDetail,
)
from personal_alpha_terminal.reports.renderer import (
    render_daily_market_report,
    render_stock_report,
)


def _instrument() -> InstrumentOption:
    return InstrumentOption(id=1, symbol="AAPL", name="Apple", market="US")


def test_daily_report_is_auditable_and_contains_no_forecast() -> None:
    document = render_daily_market_report(
        indices=(
            MarketIndexSnapshot(
                instrument=_instrument(),
                date=date(2026, 7, 30),
                close=Decimal("210.12"),
                change_pct=0.01,
                volume=1000,
                currency="USD",
                source="verified_test",
            ),
        ),
        regime=None,
        probability=None,
        portfolio=None,
    )

    assert "## Data Sources" in document.markdown
    assert "## Analytical Logic" in document.markdown
    assert "## Risk Factors and Known Limitations" in document.markdown
    assert "No price forecast" in document.markdown
    assert document.data_sources == ("prices:verified_test:US:AAPL",)


def test_stock_report_uses_adjusted_price_interval() -> None:
    detail = StockDetail(
        instrument=_instrument(),
        exchange="XNAS",
        currency="USD",
        industry="Technology",
        list_date=date(1980, 12, 12),
        is_active=True,
        prices=(
            PricePoint(
                date=date(2026, 7, 1),
                open=Decimal("99"),
                high=Decimal("101"),
                low=Decimal("98"),
                close=Decimal("100"),
                volume=100,
                source="test",
            ),
            PricePoint(
                date=date(2026, 7, 30),
                open=Decimal("109"),
                high=Decimal("111"),
                low=Decimal("108"),
                close=Decimal("110"),
                volume=120,
                source="test",
            ),
        ),
    )

    document = render_stock_report(detail)

    assert "10.00%" in document.markdown
    assert "target price" in document.markdown


def test_daily_report_names_uncalibrated_regime_output_score_not_probability() -> None:
    point = MarketRegimePoint(
        as_of_date=date(2026, 7, 30),
        regime="risk_on",
        risk_on_score=0.7,
        neutral_score=0.2,
        risk_off_score=0.1,
        composite_score=1.0,
        breadth_constituent_count=100,
        feature_values={},
        feature_zscores={},
        feature_contributions={},
    )
    regime = MarketRegimeResult(
        run_id=1,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 30),
        market="US",
        model_type="statistical",
        model_version="2.0",
        observations=(point,),
        calibration=RegimeCalibrationReport(
            status="score_only",
            method="walk_forward_fixed_bin_beta_smoothing",
            label_horizon_days=20,
            risk_on_return_threshold=0.02,
            risk_off_return_threshold=-0.02,
            training_minimum=252,
            out_of_sample_count=0,
            brier_score=None,
            raw_score_brier=None,
            baseline_brier=None,
            calibration_curve=(),
            reasons=("insufficient OOS observations",),
        ),
    )

    document = render_daily_market_report(
        indices=(
            MarketIndexSnapshot(
                instrument=_instrument(),
                date=date(2026, 7, 30),
                close=Decimal("210.12"),
                change_pct=0.01,
                volume=1000,
                currency="USD",
                source="verified_test",
            ),
        ),
        regime=regime,
        probability=None,
        portfolio=None,
    )

    assert "Market Regime Score (not probability)" in document.markdown
    assert "Calibrated Risk-On" not in document.markdown
    assert "Brier Score N/A" in document.markdown


def test_report_rejects_empty_required_data() -> None:
    with pytest.raises(ValueError, match="at least one"):
        render_daily_market_report(
            indices=(),
            regime=None,
            probability=None,
            portfolio=None,
        )
