from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from personal_alpha_terminal.analysis.market_graph.schemas import (
    GraphInstrument,
    MarketSeries,
)
from personal_alpha_terminal.analysis.market_graph.statistics import signed_flow_proxy
from personal_alpha_terminal.data.market_data.selection import (
    preferred_source,
    select_consistent_price_series,
)
from personal_alpha_terminal.models import (
    MarketGraphEdge,
    MarketGraphNode,
    MarketGraphPath,
    MarketGraphRun,
    Price,
    Stock,
)


class MarketGraphRepository:
    """Database access for graph inputs and persisted network snapshots."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_instruments(self) -> list[GraphInstrument]:
        stocks = self.session.scalars(
            select(Stock)
            .options(selectinload(Stock.industry))
            .where(
                Stock.is_active.is_(True),
                Stock.asset_type.in_(("stock", "etf", "index", "commodity")),
            )
            .order_by(Stock.asset_type, Stock.market, Stock.symbol)
        )
        return [self.instrument(stock) for stock in stocks]

    def load_series(
        self,
        instrument_ids: tuple[int, ...],
        *,
        start_date: date,
        end_date: date,
        flow_lookback_days: int,
    ) -> tuple[MarketSeries, ...]:
        stocks = list(
            self.session.scalars(
                select(Stock)
                .options(selectinload(Stock.industry))
                .where(
                    Stock.id.in_(instrument_ids),
                    Stock.is_active.is_(True),
                    Stock.asset_type.in_(("stock", "etf", "index", "commodity")),
                )
            )
        )
        stock_by_id = {stock.id: stock for stock in stocks}
        prices = self.session.scalars(
            select(Price)
            .where(
                Price.stock_id.in_(tuple(stock_by_id)),
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
        histories: defaultdict[int, list[Price]] = defaultdict(list)
        for stock_id, rows in price_rows.items():
            histories[stock_id].extend(
                select_consistent_price_series(
                    rows,
                    preferred=preferred_source(stock_by_id[stock_id].market),
                )
            )

        results: list[MarketSeries] = []
        for stock_id in instrument_ids:
            stock = stock_by_id.get(stock_id)
            if stock is None:
                continue
            history = sorted(histories.get(stock_id, []), key=lambda item: item.trade_date)
            returns: list[tuple[date, float]] = []
            flow_values: list[tuple[date, float]] = []
            for index in range(1, len(history)):
                previous = history[index - 1]
                current = history[index]
                if current.trade_date < start_date:
                    continue
                previous_close = float(previous.adjusted_close or previous.close)
                current_close = float(current.adjusted_close or current.close)
                if previous_close <= 0:
                    continue
                daily_return = current_close / previous_close - 1
                returns.append((current.trade_date, daily_return))
                volume_window = history[max(0, index - flow_lookback_days) : index]
                prior_volumes = [item.volume for item in volume_window if item.volume is not None]
                if len(prior_volumes) != flow_lookback_days:
                    continue
                proxy = signed_flow_proxy(
                    daily_return,
                    current.volume,
                    prior_volumes,
                )
                if proxy is not None:
                    flow_values.append((current.trade_date, proxy))
            results.append(
                MarketSeries(
                    instrument=self.instrument(stock),
                    returns=tuple(returns),
                    flow_proxy=tuple(flow_values),
                )
            )
        return tuple(results)

    def latest_run(self) -> MarketGraphRun | None:
        return self.session.scalar(
            select(MarketGraphRun)
            .where(MarketGraphRun.status == "completed")
            .order_by(MarketGraphRun.created_at.desc(), MarketGraphRun.id.desc())
            .limit(1)
        )

    def nodes_for_run(self, run_id: int) -> list[MarketGraphNode]:
        return list(
            self.session.scalars(
                select(MarketGraphNode)
                .where(MarketGraphNode.run_id == run_id)
                .order_by(MarketGraphNode.core_score.desc())
            )
        )

    def edges_for_run(self, run_id: int) -> list[MarketGraphEdge]:
        return list(
            self.session.scalars(
                select(MarketGraphEdge)
                .where(MarketGraphEdge.run_id == run_id)
                .order_by(MarketGraphEdge.relationship_type, MarketGraphEdge.strength.desc())
            )
        )

    def paths_for_run(self, run_id: int) -> list[MarketGraphPath]:
        return list(
            self.session.scalars(
                select(MarketGraphPath)
                .where(MarketGraphPath.run_id == run_id)
                .order_by(MarketGraphPath.path_rank)
            )
        )

    @staticmethod
    def instrument(stock: Stock) -> GraphInstrument:
        return GraphInstrument(
            id=stock.id,
            key=f"{stock.asset_type}:{stock.id}",
            symbol=stock.symbol,
            name=stock.name,
            market=stock.market,
            asset_type=stock.asset_type,
            industry=stock.industry.name if stock.industry else None,
        )
