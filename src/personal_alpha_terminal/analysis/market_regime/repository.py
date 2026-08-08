from collections import defaultdict
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from personal_alpha_terminal.analysis.market_graph.repository import MarketGraphRepository
from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument
from personal_alpha_terminal.analysis.market_regime.schemas import (
    RegimeAssetSeries,
    RegimeMarketData,
    RegimePricePoint,
    RegimeUniversePoint,
)
from personal_alpha_terminal.data.market_data.selection import (
    preferred_source,
    select_consistent_price_series,
)
from personal_alpha_terminal.models import (
    MarketRegimeObservation,
    MarketRegimeRun,
    MarketUniverseMember,
    MarketUniverseSnapshot,
    Price,
    Stock,
)


class MarketRegimeRepository:
    """Load regime drivers and persist model snapshots."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_instruments(self) -> list[GraphInstrument]:
        stocks = self.session.scalars(
            select(Stock)
            .options(selectinload(Stock.industry))
            .where(Stock.is_active.is_(True))
            .order_by(Stock.market, Stock.asset_type, Stock.symbol)
        )
        return [MarketGraphRepository.instrument(stock) for stock in stocks]

    def load_market_data(
        self,
        *,
        vix_stock_id: int,
        rate_stock_id: int,
        dollar_stock_id: int,
        benchmark_stock_id: int,
        market: str,
        query_start_date: date,
        end_date: date,
        maximum_breadth_assets: int,
    ) -> RegimeMarketData:
        driver_ids = (
            vix_stock_id,
            rate_stock_id,
            dollar_stock_id,
            benchmark_stock_id,
        )
        drivers = list(
            self.session.scalars(
                select(Stock)
                .options(selectinload(Stock.industry))
                .where(Stock.id.in_(driver_ids))
            )
        )
        if len(drivers) != len(set(driver_ids)):
            raise ValueError("one or more selected regime driver instruments do not exist")
        driver_by_id = {stock.id: stock for stock in drivers}

        snapshot_models = list(
            self.session.scalars(
                select(MarketUniverseSnapshot)
                .where(
                    MarketUniverseSnapshot.market == market,
                    MarketUniverseSnapshot.as_of_date <= end_date,
                    MarketUniverseSnapshot.available_time
                    <= datetime.combine(end_date, datetime.max.time(), UTC),
                )
                .order_by(MarketUniverseSnapshot.as_of_date, MarketUniverseSnapshot.available_time)
            )
        )
        if not snapshot_models:
            raise ValueError(
                "SURVIVORSHIP_BIAS_RISK: regime breadth requires point-in-time universe snapshots"
            )
        snapshot_ids = tuple(item.id for item in snapshot_models)
        member_rows = list(
            self.session.execute(
                select(MarketUniverseMember.snapshot_id, MarketUniverseMember.stock_id).where(
                    MarketUniverseMember.snapshot_id.in_(snapshot_ids)
                )
            )
        )
        members_by_snapshot: defaultdict[int, set[int]] = defaultdict(set)
        for snapshot_id, stock_id in member_rows:
            members_by_snapshot[snapshot_id].add(stock_id)
        breadth_ids = tuple(
            sorted(
                {
                    stock_id
                    for values in members_by_snapshot.values()
                    for stock_id in values
                }
            )
        )
        breadth_stocks = list(
            self.session.scalars(
                select(Stock)
                .options(selectinload(Stock.industry))
                .where(
                    Stock.id.in_(breadth_ids),
                    Stock.market == market,
                    Stock.asset_type == "stock",
                )
                .order_by(Stock.id)
            )
        )
        if len(breadth_stocks) > maximum_breadth_assets:
            raise ValueError(
                f"breadth universe exceeds configured maximum ({maximum_breadth_assets})"
            )
        all_stocks = {stock.id: stock for stock in [*drivers, *breadth_stocks]}
        prices = self.session.scalars(
            select(Price)
            .where(
                Price.stock_id.in_(tuple(all_stocks)),
                Price.trade_date >= query_start_date,
                Price.trade_date <= end_date,
            )
            .order_by(
                Price.stock_id,
                Price.trade_date,
                Price.ingested_at.desc(),
                Price.source,
            )
        )
        price_rows: defaultdict[int, list[Price]] = defaultdict(list)
        for price in prices:
            price_rows[price.stock_id].append(price)
        histories: defaultdict[int, list[RegimePricePoint]] = defaultdict(list)
        for stock_id, rows in price_rows.items():
            for price in select_consistent_price_series(
                rows,
                preferred=preferred_source(all_stocks[stock_id].market),
            ):
                close = float(price.adjusted_close or price.close)
                if close <= 0:
                    continue
                histories[stock_id].append(
                    RegimePricePoint(
                        date=price.trade_date,
                        close=close,
                        volume=price.volume,
                    )
                )

        def series(stock: Stock) -> RegimeAssetSeries:
            return RegimeAssetSeries(
                instrument=MarketGraphRepository.instrument(stock),
                prices=tuple(sorted(histories.get(stock.id, []), key=lambda item: item.date)),
            )

        return RegimeMarketData(
            vix=series(driver_by_id[vix_stock_id]),
            rate=series(driver_by_id[rate_stock_id]),
            dollar=series(driver_by_id[dollar_stock_id]),
            benchmark=series(driver_by_id[benchmark_stock_id]),
            breadth_constituents=tuple(series(stock) for stock in breadth_stocks),
            breadth_universe_timeline=tuple(
                RegimeUniversePoint(
                    snapshot_id=item.id,
                    as_of_date=item.as_of_date,
                    available_at=item.available_time,
                    asset_ids=frozenset(members_by_snapshot[item.id]),
                    source=f"{item.source}:{item.provider}",
                )
                for item in snapshot_models
            ),
            calibration_eligible=False,
            calibration_limitations=(
                "PIT breadth snapshots are present but have not passed independent "
                "historical certification",
                "price/action history has not passed the production historical-data gate",
            ),
        )

    def latest_run(self) -> MarketRegimeRun | None:
        return self.session.scalar(
            select(MarketRegimeRun)
            .where(MarketRegimeRun.status == "completed")
            .order_by(MarketRegimeRun.created_at.desc(), MarketRegimeRun.id.desc())
            .limit(1)
        )

    def observations_for_run(self, run_id: int) -> list[MarketRegimeObservation]:
        return list(
            self.session.scalars(
                select(MarketRegimeObservation)
                .where(MarketRegimeObservation.run_id == run_id)
                .order_by(MarketRegimeObservation.as_of_date)
            )
        )
