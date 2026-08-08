from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.analysis.market_regime.repository import (
    MarketRegimeRepository,
)
from personal_alpha_terminal.analysis.market_regime.service import MarketRegimeService
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import (
    MarketRegimeObservation,
    MarketRegimeRun,
    MarketUniverseMember,
    MarketUniverseSnapshot,
    Price,
    Stock,
)


def add_instrument(
    session: Session,
    symbol: str,
    closes: list[float],
    *,
    asset_type: str,
    volumes: list[int] | None = None,
) -> Stock:
    stock = Stock(
        canonical_code=f"US:TEST:{symbol}",
        symbol=symbol,
        name=symbol,
        market="US",
        exchange="TEST",
        asset_type=asset_type,
        currency="USD",
        timezone="America/New_York",
    )
    session.add(stock)
    start = date(2025, 1, 1)
    for index, close in enumerate(closes):
        trade_date = start + timedelta(days=index)
        value = Decimal(str(close))
        session.add(
            Price(
                stock=stock,
                trade_date=trade_date,
                open=value,
                high=value,
                low=value,
                close=value,
                adjusted_close=value,
                volume=volumes[index] if volumes else 1_000_000,
                source="yahoo_finance",
                ingested_at=datetime.combine(trade_date, datetime.min.time(), UTC),
            )
        )
    return stock


def build_closes(count: int, *, risk_off_return: float) -> list[float]:
    close = 100.0
    values: list[float] = []
    for index in range(count):
        daily_return = risk_off_return if index >= 120 else ((index % 7) - 3) / 1000
        close *= 1 + daily_return
        values.append(close)
    return values


def test_market_regime_run_persists_scores_and_blocks_unproved_probabilities(
    session_factory: sessionmaker[Session],
) -> None:
    count = 150
    with session_factory() as session:
        vix = add_instrument(
            session,
            "^VIX",
            [
                20 + ((index % 7) - 3) / 10 if index < 120 else 22 + (index - 120) * 0.7
                for index in range(count)
            ],
            asset_type="index",
        )
        rate = add_instrument(
            session,
            "^TNX",
            [
                4 + ((index % 5) - 2) / 100 if index < 120 else 4.1 + (index - 120) * 0.04
                for index in range(count)
            ],
            asset_type="index",
        )
        dollar = add_instrument(
            session,
            "DXY",
            [
                100 + ((index % 6) - 3) / 10 if index < 120 else 101 + (index - 120) * 0.3
                for index in range(count)
            ],
            asset_type="index",
        )
        benchmark = add_instrument(
            session,
            "^GSPC",
            build_closes(count, risk_off_return=-0.008),
            asset_type="index",
        )
        first = add_instrument(
            session,
            "AAA",
            build_closes(count, risk_off_return=-0.01),
            asset_type="stock",
            volumes=[1_000_000 + index * 1_000 for index in range(count)],
        )
        second = add_instrument(
            session,
            "BBB",
            build_closes(count, risk_off_return=-0.012),
            asset_type="stock",
            volumes=[800_000 + index * 1_000 for index in range(count)],
        )
        session.flush()
        universe = MarketUniverseSnapshot(
            market="US",
            as_of_date=date(2025, 1, 1),
            source="fixture",
            provider="deterministic_test",
            available_time=datetime(2025, 1, 1, 22, tzinfo=UTC),
            ingested_time=datetime(2025, 1, 1, 23, tzinfo=UTC),
        )
        universe.members.extend(
            [
                MarketUniverseMember(
                    stock_id=stock.id,
                    segment="test",
                    size_bucket="large",
                    listing_age_bucket="seasoned",
                    market_cap=None,
                    reason="point-in-time fixture membership",
                )
                for stock in (first, second)
            ]
        )
        session.add(universe)
        session.commit()

        settings = Settings(
            _env_file=None,
            regime_rate_change_window=5,
            regime_dollar_trend_window=5,
            regime_index_trend_window=10,
            regime_breadth_window=10,
            regime_calibration_window=40,
            regime_minimum_calibration_observations=30,
            regime_minimum_breadth_assets=2,
            regime_maximum_breadth_assets=10,
            regime_probability_label_horizon=5,
            regime_probability_return_threshold=0.005,
            regime_probability_minimum_training_observations=30,
            regime_probability_minimum_oos_observations=30,
            regime_probability_minimum_class_observations=2,
            regime_probability_minimum_bin_observations=2,
        )
        service = MarketRegimeService(MarketRegimeRepository(session), settings)
        result = service.run(
            vix_stock_id=vix.id,
            rate_stock_id=rate.id,
            dollar_stock_id=dollar.id,
            benchmark_stock_id=benchmark.id,
            market="US",
            start_date=date(2025, 4, 21),
            end_date=date(2025, 5, 30),
        )
        session.commit()

        current = result.current
        assert current.regime == "risk_off"
        assert current.risk_off_score > current.neutral_score
        assert current.probabilities is None
        assert result.calibration.status == "score_only"
        assert result.calibration.reasons
        assert not any("current active stocks" in item for item in result.calibration.reasons)
        assert current.breadth_constituent_count == 2
        assert set(current.feature_values) == {
            "vix_level",
            "rate_change",
            "dollar_trend",
            "index_trend",
            "market_breadth",
            "volume_breadth",
        }
        assert (
            current.risk_on_score + current.risk_off_score + current.neutral_score
        ) == pytest.approx(1)
        assert session.scalar(select(func.count(MarketRegimeRun.id))) == 1
        assert session.scalar(select(func.count(MarketRegimeObservation.id))) == len(
            result.observations
        )

        restored = service.latest()
        assert restored is not None
        assert restored.run_id == result.run_id
        assert restored.current.regime == "risk_off"
        assert restored.current.probabilities is None
        assert restored.calibration.status == "score_only"
        assert first.id != second.id
