from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.core.data_timestamps import daily_bar_timestamps
from personal_alpha_terminal.data.market_data_quality.repository import (
    MarketDataQualityRepository,
)
from personal_alpha_terminal.data.market_data_quality.sampling import (
    DEFAULT_SAMPLING_PLAN,
)
from personal_alpha_terminal.data.market_data_quality.schemas import MarketSegment
from personal_alpha_terminal.data.market_data_quality.service import (
    MarketDataQualityService,
)
from personal_alpha_terminal.models import (
    ExchangeSession,
    MarketDataQualityResult,
    MarketDataQualityRun,
    MarketUniverseMember,
    MarketUniverseSnapshot,
    Price,
    Stock,
)

MARKET_BY_SEGMENT = {
    MarketSegment.SSE_MAIN: "A",
    MarketSegment.SZSE_MAIN: "A",
    MarketSegment.CHINEXT: "A",
    MarketSegment.STAR: "A",
    MarketSegment.A_ETF: "A",
    MarketSegment.NYSE: "US",
    MarketSegment.NASDAQ: "US",
    MarketSegment.US_ETF: "US",
    MarketSegment.HK_MAIN: "HK",
    MarketSegment.HK_ETF: "HK",
}

EXCHANGE_BY_SEGMENT = {
    MarketSegment.SSE_MAIN: "SSE",
    MarketSegment.SZSE_MAIN: "SZSE",
    MarketSegment.CHINEXT: "SZSE",
    MarketSegment.STAR: "SSE",
    MarketSegment.A_ETF: "SSE",
    MarketSegment.NYSE: "NYSE",
    MarketSegment.NASDAQ: "NASDAQ",
    MarketSegment.US_ETF: "NASDAQ",
    MarketSegment.HK_MAIN: "HKEX",
    MarketSegment.HK_ETF: "HKEX",
}


def seed_quality_dataset(session: Session) -> None:
    start = date(2020, 1, 2)
    end = date(2020, 1, 3)
    timestamp = datetime(2020, 1, 3, tzinfo=UTC)
    snapshots = {
        market: MarketUniverseSnapshot(
            market=market,
            as_of_date=end,
            source=f"{market.lower()}_official_list",
            provider="fixture.official_snapshot",
            available_time=timestamp,
            ingested_time=timestamp,
        )
        for market in ("A", "HK", "US")
    }
    session.add_all(snapshots.values())
    session.flush()

    stock_id = 0
    for segment, quota in DEFAULT_SAMPLING_PLAN.segment_quotas.items():
        market = MARKET_BY_SEGMENT[segment]
        exchange = EXCHANGE_BY_SEGMENT[segment]
        for _index in range(quota):
            stock_id += 1
            is_etf = segment.value.endswith("etf")
            symbol = (
                f"{stock_id:06d}"
                if market == "A"
                else f"{stock_id:05d}"
                if market == "HK"
                else f"S{stock_id:04d}"
            )
            stock = Stock(
                canonical_code=f"{market}:{exchange}:{symbol}",
                symbol=symbol,
                name=f"Security {stock_id}",
                market=market,
                exchange=exchange,
                asset_type="etf" if is_etf else "stock",
                currency={"A": "CNY", "HK": "HKD", "US": "USD"}[market],
                timezone={
                    "A": "Asia/Shanghai",
                    "HK": "Asia/Hong_Kong",
                    "US": "America/New_York",
                }[market],
                list_date=start,
                delist_date=end if stock_id <= 5 else None,
                is_active=stock_id > 5,
                source=f"{market.lower()}_official_list",
                provider="fixture.official_security_master",
                available_time=timestamp,
                ingested_time=timestamp,
            )
            session.add(stock)
            session.flush()
            session.add(
                MarketUniverseMember(
                    snapshot_id=snapshots[market].id,
                    stock_id=stock.id,
                    segment=segment.value,
                    size_bucket="large" if stock_id % 2 else "mid_small",
                    listing_age_bucket="new" if stock_id <= 5 else "established",
                    market_cap=Decimal("1000000000"),
                    reason="listed_on_snapshot_date",
                )
            )
            for trade_date, close in ((start, Decimal("10")), (end, Decimal("10.1"))):
                times = daily_bar_timestamps(trade_date, market)
                session.add(
                    Price(
                        stock_id=stock.id,
                        trade_date=trade_date,
                        open=close,
                        high=close,
                        low=close,
                        close=close,
                        adjusted_close=close,
                        volume=1000,
                        source={
                            "A": "akshare",
                            "HK": "yahoo_finance",
                            "US": "yahoo_finance",
                        }[market],
                        provider="fixture.independent_feed",
                        adjustment_method="point_in_time_total_return",
                        event_time=times.event_time,
                        available_time=times.available_time,
                        ingested_at=times.ingested_time,
                    )
                )

    for exchange in sorted(set(EXCHANGE_BY_SEGMENT.values())):
        for session_date in (start, end):
            session.add(
                ExchangeSession(
                    exchange=exchange,
                    session_date=session_date,
                    is_open=True,
                    open_time=datetime(2020, 1, 2, 1, 30, tzinfo=UTC),
                    close_time=datetime(2020, 1, 2, 8, 0, tzinfo=UTC),
                    timezone={
                        "SSE": "Asia/Shanghai",
                        "SZSE": "Asia/Shanghai",
                        "NYSE": "America/New_York",
                        "NASDAQ": "America/New_York",
                        "HKEX": "Asia/Hong_Kong",
                    }[exchange],
                    source=f"{exchange.lower()}_official_calendar",
                    provider="fixture.official_calendar",
                    available_time=timestamp,
                    ingested_time=timestamp,
                )
            )
    session.commit()


def test_quality_service_samples_100_and_persists_results(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        seed_quality_dataset(session)
        service = MarketDataQualityService(MarketDataQualityRepository(session))

        run_id, report = service.run(
            history_start=date(2020, 1, 2),
            history_end=date(2020, 1, 3),
            seed=11,
        )
        session.commit()

        assert report.status.value == "passed"
        assert report.sample is not None
        assert len(report.sample.selected) == 100
        assert report.missing_rate == 0
        assert report.anomaly_rate == 0
        assert report.provider_counts == {"fixture.independent_feed": 200}
        assert session.scalar(select(func.count()).select_from(MarketDataQualityRun)) == 1
        assert (
            session.scalar(select(func.count()).select_from(MarketDataQualityResult))
            == 100
        )
        persisted = session.get(MarketDataQualityRun, run_id)
        assert persisted is not None
        assert persisted.status == "passed"
