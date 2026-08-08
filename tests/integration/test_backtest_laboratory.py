from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.backtest.repository import BacktestRepository
from personal_alpha_terminal.backtest.schemas import (
    BacktestBar,
    BacktestConfig,
    BacktestDataset,
    StrategyContext,
    TargetAllocation,
)
from personal_alpha_terminal.backtest.service import BacktestService
from personal_alpha_terminal.core.data_timestamps import daily_bar_timestamps
from personal_alpha_terminal.models import (
    BacktestDailyResult,
    BacktestRebalance,
    BacktestRun,
    BacktestSummaryMetric,
    MarketDataQualityRun,
    MarketUniverseMember,
    MarketUniverseSnapshot,
    Price,
    ResearchReport,
    Stock,
)
from personal_alpha_terminal.reports.service import ResearchReportService


@dataclass(frozen=True)
class BuyAndHold:
    first_date: date

    @property
    def name(self) -> str:
        return "buy_and_hold_fixture"

    def generate_targets(self, context: StrategyContext) -> TargetAllocation | None:
        if context.signal_date == self.first_date:
            return TargetAllocation({1: 1.0}, ("audited_fixture",))
        return None

    def audit_payload(self) -> dict[str, object]:
        return {
            "type": "buy_and_hold_fixture",
            "first_date": self.first_date.isoformat(),
        }


def _business_dates(start: date, count: int) -> tuple[date, ...]:
    output: list[date] = []
    current = start
    while len(output) < count:
        if current.weekday() < 5:
            output.append(current)
        current += timedelta(days=1)
    return tuple(output)


def test_backtest_service_persists_daily_ledger_metrics_and_report(
    session_factory: sessionmaker[Session],
) -> None:
    first_date = date(2024, 1, 2)
    calendar = _business_dates(first_date, 30)
    bars = tuple(
        BacktestBar(
            asset_id=1,
            symbol="TEST",
            market="US",
            trade_date=trade_date,
            open=100 + offset,
            high=100 + offset,
            low=100 + offset,
            close=100 + offset,
            adjusted_close=100 + offset,
            volume=1_000_000,
            source="fixture",
            adjustment_method="point_in_time_total_return",
            provider="fixture",
            event_time=daily_bar_timestamps(trade_date, "US").event_time,
            available_time=daily_bar_timestamps(trade_date, "US").available_time,
            ingested_time=daily_bar_timestamps(trade_date, "US").ingested_time,
            open_tradable=True,
        )
        for offset, trade_date in enumerate(calendar)
    )
    config = BacktestConfig(
        start_date=bars[0].trade_date,
        end_date=bars[-1].trade_date,
        rebalance_frequency="daily",
        initial_capital=10_000,
        minimum_sessions=20,
        liquidity_lookback_sessions=2,
        minimum_liquidity_observations=1,
        maximum_adv_participation=1.0,
    )

    with session_factory() as session:
        service = BacktestService(
            BacktestRepository(session),
            ResearchReportService(session),
        )
        result, report = service.run(
            BacktestDataset(
                "US",
                bars,
                ("synthetic:integration_fixture",),
                calendar=calendar,
                calendar_source="test_business_day_fixture",
            ),
            BuyAndHold(first_date),
            config,
        )
        session.commit()

        assert result.run_id is not None
        assert report.subject_key == str(result.run_id)
        assert session.scalar(select(func.count(BacktestRun.id))) == 1
        assert session.scalar(select(func.count(BacktestDailyResult.id))) == 30
        assert session.scalar(select(func.count(BacktestRebalance.id))) == 1
        assert session.scalar(select(func.count(BacktestSummaryMetric.id))) == 1
        assert (
            session.scalar(
                select(func.count(ResearchReport.id)).where(
                    ResearchReport.report_type == "strategy_backtest"
                )
            )
            == 1
        )


def test_backtest_database_flow_selects_prices_and_generates_net_result(
    session_factory: sessionmaker[Session],
) -> None:
    first_date = date(2024, 1, 2)
    calendar = _business_dates(first_date, 30)
    with session_factory() as session:
        stock = Stock(
            canonical_code="US:XNAS:TEST",
            symbol="TEST",
            name="Test Asset",
            market="US",
            exchange="XNAS",
            asset_type="stock",
            currency="USD",
            timezone="America/New_York",
        )
        session.add(stock)
        session.flush()
        snapshot = MarketUniverseSnapshot(
            market="US",
            as_of_date=date(2023, 12, 29),
            source="fixture_universe",
            provider="fixture_provider",
            available_time=datetime(2023, 12, 29, 22, tzinfo=UTC),
            ingested_time=datetime(2023, 12, 29, 23, tzinfo=UTC),
        )
        session.add(snapshot)
        session.flush()
        session.add(
            MarketUniverseMember(
                snapshot_id=snapshot.id,
                stock_id=stock.id,
                segment="nasdaq",
                size_bucket="large",
                listing_age_bucket="established",
                reason="point_in_time_fixture",
            )
        )
        decision_time = datetime(2024, 3, 1, 22, tzinfo=UTC)
        session.add(
            MarketDataQualityRun(
                history_start=date(2023, 12, 29),
                history_end=date(2024, 3, 1),
                random_seed=41,
                minimum_sample_size=1,
                sample_count=1,
                status="passed",
                source_snapshot_ids=[snapshot.id],
                aggregate_metrics={
                    "source": "fixture_universe",
                    "provider": "fixture_provider",
                    "latest_available_time": datetime(2024, 2, 29, 22, tzinfo=UTC).isoformat(),
                    "missing_rate": 0.0,
                    "anomaly_rate": 0.0,
                    "maximum_missing_rate": 0.01,
                    "maximum_anomaly_rate": 0.005,
                    "data_version": "fixture-pit-v1",
                    "us_point_in_time_status": "certified",
                    "us_adjustment_mode": "point_in_time_total_return",
                    "us_corporate_actions_certified": True,
                    "us_trading_calendar_certified": True,
                    "us_dual_source_verified": True,
                    "allow_backtest": True,
                    "allow_display": True,
                    "allow_portfolio_decision": False,
                },
                blockers=[],
            )
        )
        session.add_all(
            [
                Price(
                    stock_id=stock.id,
                    trade_date=trade_date,
                    open=Decimal(str(100 + offset)),
                    high=Decimal(str(100 + offset)),
                    low=Decimal(str(100 + offset)),
                    close=Decimal(str(100 + offset)),
                    adjusted_close=Decimal(str(100 + offset)),
                    volume=1_000_000,
                    source="yahoo_finance",
                    provider="fixture.point_in_time_actions",
                    adjustment_method="point_in_time_total_return",
                    event_time=daily_bar_timestamps(
                        trade_date,
                        "US",
                    ).event_time,
                    available_time=daily_bar_timestamps(
                        trade_date,
                        "US",
                    ).available_time,
                    open_tradable=True,
                )
                for offset, trade_date in enumerate(calendar)
            ]
        )
        session.flush()
        config = BacktestConfig(
            start_date=first_date,
            end_date=calendar[-1],
            rebalance_frequency="daily",
            initial_capital=10_000,
            minimum_sessions=20,
            liquidity_lookback_sessions=2,
            minimum_liquidity_observations=1,
            maximum_adv_participation=1.0,
        )
        service = BacktestService(
            BacktestRepository(session),
            ResearchReportService(session),
        )
        result, _report = service.run_from_database(
            market="US",
            universe_snapshot_id=snapshot.id,
            decision_time=decision_time,
            strategy=BuyAndHold(first_date),
            config=config,
            calendar=calendar,
            calendar_source="test_business_day_fixture",
        )
        session.commit()

        assert result.metrics.total_return > 0
        assert result.data_fingerprint
        assert result.rebalances[0].execution_date == calendar[1]
