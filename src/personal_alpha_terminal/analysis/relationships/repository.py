from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.analysis.relationships.schemas import (
    EntityOption,
    EntityReturns,
)
from personal_alpha_terminal.data.market_data.selection import (
    preferred_source,
    select_consistent_price_series,
)
from personal_alpha_terminal.models import (
    Industry,
    Price,
    RelationshipAnalysisRun,
    RelationshipAnomaly,
    RelationshipCorrelation,
    Stock,
)


class RelationshipRepository:
    """Database access for relationship inputs and persisted research outputs."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_entities(self, universe_type: str) -> list[EntityOption]:
        if universe_type in {"stock", "etf"}:
            stocks = self.session.scalars(
                select(Stock)
                .where(
                    Stock.is_active.is_(True),
                    Stock.asset_type == universe_type,
                )
                .order_by(Stock.market, Stock.symbol)
            )
            return [
                EntityOption(
                    id=stock.id,
                    entity_type=universe_type,
                    key=f"{universe_type}:{stock.id}",
                    label=f"{stock.symbol} · {stock.name} ({stock.market})",
                )
                for stock in stocks
            ]
        if universe_type == "industry":
            industries = self.session.scalars(
                select(Industry)
                .join(Stock, Stock.industry_id == Industry.id)
                .where(Stock.is_active.is_(True), Stock.asset_type == "stock")
                .distinct()
                .order_by(Industry.taxonomy, Industry.name)
            )
            return [
                EntityOption(
                    id=industry.id,
                    entity_type="industry",
                    key=f"industry:{industry.id}",
                    label=f"{industry.taxonomy} · {industry.name}",
                )
                for industry in industries
            ]
        raise ValueError(f"unsupported universe type: {universe_type}")

    def load_returns(
        self,
        universe_type: str,
        entity_ids: tuple[int, ...],
        *,
        start_date: date,
        end_date: date,
    ) -> tuple[EntityReturns, ...]:
        options = {
            option.id: option
            for option in self.list_entities(universe_type)
            if option.id in entity_ids
        }
        if universe_type in {"stock", "etf"}:
            stock_ids = tuple(options)
            stock_returns = self._stock_returns(stock_ids, start_date, end_date)
            return tuple(
                EntityReturns(option=options[stock_id], values=stock_returns.get(stock_id, ()))
                for stock_id in entity_ids
                if stock_id in options
            )

        stock_rows = self.session.execute(
            select(Stock.id, Stock.industry_id).where(
                Stock.is_active.is_(True),
                Stock.asset_type == "stock",
                Stock.industry_id.in_(tuple(options)),
            )
        )
        stock_to_industry = {
            stock_id: industry_id for stock_id, industry_id in stock_rows if industry_id is not None
        }
        stock_returns = self._stock_returns(
            tuple(stock_to_industry),
            start_date,
            end_date,
        )
        daily_members: defaultdict[tuple[int, date], list[float]] = defaultdict(list)
        for stock_id, values in stock_returns.items():
            industry_id = stock_to_industry[stock_id]
            for observation_date, value in values:
                daily_members[(industry_id, observation_date)].append(value)

        industry_values: defaultdict[int, list[tuple[date, float]]] = defaultdict(list)
        for (industry_id, observation_date), member_returns in daily_members.items():
            industry_values[industry_id].append(
                (
                    observation_date,
                    sum(member_returns) / len(member_returns),
                )
            )
        return tuple(
            EntityReturns(
                option=options[industry_id],
                values=tuple(sorted(industry_values.get(industry_id, []))),
            )
            for industry_id in entity_ids
            if industry_id in options
        )

    def latest_run(
        self,
        universe_type: str,
        method: str,
    ) -> RelationshipAnalysisRun | None:
        return self.session.scalar(
            select(RelationshipAnalysisRun)
            .where(
                RelationshipAnalysisRun.universe_type == universe_type,
                RelationshipAnalysisRun.method == method,
                RelationshipAnalysisRun.status == "completed",
            )
            .order_by(RelationshipAnalysisRun.created_at.desc(), RelationshipAnalysisRun.id.desc())
            .limit(1)
        )

    def correlations_for_run(self, run_id: int) -> list[RelationshipCorrelation]:
        return list(
            self.session.scalars(
                select(RelationshipCorrelation)
                .where(RelationshipCorrelation.run_id == run_id)
                .order_by(
                    RelationshipCorrelation.window_days,
                    RelationshipCorrelation.as_of_date,
                    RelationshipCorrelation.left_entity_key,
                    RelationshipCorrelation.right_entity_key,
                )
            )
        )

    def anomalies_for_run(self, run_id: int) -> list[RelationshipAnomaly]:
        return list(
            self.session.scalars(
                select(RelationshipAnomaly)
                .where(RelationshipAnomaly.run_id == run_id)
                .order_by(RelationshipAnomaly.absolute_change.desc())
            )
        )

    def _stock_returns(
        self,
        stock_ids: tuple[int, ...],
        start_date: date,
        end_date: date,
    ) -> dict[int, tuple[tuple[date, float], ...]]:
        if not stock_ids:
            return {}
        prices = self.session.scalars(
            select(Price)
            .where(
                Price.stock_id.in_(stock_ids),
                Price.trade_date >= start_date - timedelta(days=31),
                Price.trade_date <= end_date,
            )
            .order_by(
                Price.stock_id,
                Price.trade_date,
                Price.ingested_at.desc(),
                Price.source,
            )
        )
        market_by_stock_id: dict[int, str] = {
            stock_id: market
            for stock_id, market in self.session.execute(
                select(Stock.id, Stock.market).where(Stock.id.in_(stock_ids))
            )
        }
        price_rows: defaultdict[int, list[Price]] = defaultdict(list)
        for price in prices:
            price_rows[price.stock_id].append(price)

        histories: defaultdict[int, list[tuple[date, float]]] = defaultdict(list)
        for stock_id, rows in price_rows.items():
            for price in select_consistent_price_series(
                rows,
                preferred=preferred_source(market_by_stock_id[stock_id]),
            ):
                histories[stock_id].append(
                    (
                        price.trade_date,
                        float(price.adjusted_close or price.close),
                    )
                )

        results: dict[int, tuple[tuple[date, float], ...]] = {}
        for stock_id, history in histories.items():
            ordered = sorted(history)
            returns: list[tuple[date, float]] = []
            for previous, current in zip(ordered, ordered[1:], strict=False):
                if current[0] >= start_date and previous[1] > 0:
                    returns.append((current[0], current[1] / previous[1] - 1))
            results[stock_id] = tuple(returns)
        return results
