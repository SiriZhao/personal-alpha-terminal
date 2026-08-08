from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from personal_alpha_terminal.analysis.factors.schemas import (
    FactorAssetData,
    FactorDataset,
    FactorFinancialPoint,
    FactorPricePoint,
)
from personal_alpha_terminal.analysis.market_graph.repository import MarketGraphRepository
from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument
from personal_alpha_terminal.core.data_timestamps import DataTimestamps
from personal_alpha_terminal.core.market_time import normalize_utc
from personal_alpha_terminal.data.market_data.selection import (
    preferred_source,
    select_consistent_price_series,
)
from personal_alpha_terminal.data.market_data_quality.schemas import AdjustmentMode
from personal_alpha_terminal.models import (
    FactorBacktestPeriod,
    FactorBacktestSummary,
    FactorResearchRun,
    FactorScore,
    FundamentalVintage,
    MarketUniverseMember,
    MarketUniverseSnapshot,
    Price,
    Stock,
)


def _numeric_value(values: Mapping[str, object], name: str) -> float | None:
    value = values.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


class FactorResearchRepository:
    """Load point-in-time factor inputs and persisted research results."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def load_dataset(
        self,
        *,
        market: str,
        query_start_date: date,
        end_date: date,
        include_inactive: bool,
        maximum_universe_size: int,
        universe_snapshot_id: int | None = None,
    ) -> FactorDataset:
        del include_inactive
        if universe_snapshot_id is None:
            raise ValueError(
                "SURVIVORSHIP_BIAS_RISK: factor research requires an explicit "
                "point-in-time universe snapshot"
            )
        snapshot = self.session.get(MarketUniverseSnapshot, universe_snapshot_id)
        cutoff = datetime.combine(end_date, datetime.max.time(), UTC)
        if snapshot is None or snapshot.market != market:
            raise ValueError("point-in-time universe snapshot is missing or for another market")
        if snapshot.as_of_date > end_date or normalize_utc(snapshot.available_time) > cutoff:
            raise ValueError("point-in-time universe snapshot was not available at the cutoff")
        member_ids = tuple(
            self.session.scalars(
                select(MarketUniverseMember.stock_id).where(
                    MarketUniverseMember.snapshot_id == universe_snapshot_id
                )
            )
        )
        if not member_ids:
            return FactorDataset(assets=())
        statement = (
            select(Stock)
            .options(selectinload(Stock.industry))
            .where(
                Stock.id.in_(member_ids),
                Stock.market == market,
                Stock.asset_type == "stock",
            )
            .order_by(Stock.id)
        )
        stocks = list(self.session.scalars(statement))
        if len(stocks) > maximum_universe_size:
            raise ValueError(
                f"factor universe exceeds configured maximum ({maximum_universe_size})"
            )
        if not stocks:
            return FactorDataset(assets=())
        stock_ids = tuple(stock.id for stock in stocks)
        price_models = self.session.scalars(
            select(Price)
            .where(
                Price.stock_id.in_(stock_ids),
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
        for price in price_models:
            price_rows[price.stock_id].append(price)
        prices: defaultdict[int, list[FactorPricePoint]] = defaultdict(list)
        stock_by_id = {stock.id: stock for stock in stocks}
        for stock_id, rows in price_rows.items():
            for price in select_consistent_price_series(
                rows,
                preferred=preferred_source(stock_by_id[stock_id].market),
            ):
                if (
                    price.adjusted_close is None
                    or price.adjustment_method
                    != AdjustmentMode.POINT_IN_TIME_TOTAL_RETURN.value
                ):
                    raise ValueError(
                        "factor research requires point-in-time total-return prices; "
                        "provider current-snapshot adjustments can leak later corporate "
                        "actions into historical formation dates: "
                        f"stock_id={stock_id} date={price.trade_date} "
                        f"method={price.adjustment_method!r}"
                    )
                close = float(price.adjusted_close)
                if close > 0:
                    prices[stock_id].append(
                        FactorPricePoint(
                            date=price.trade_date,
                            close=close,
                            raw_close=float(price.close),
                        )
                    )

        available_end = datetime.combine(end_date, datetime.max.time(), UTC)
        financial_models = self.session.scalars(
            select(FundamentalVintage)
            .where(
                FundamentalVintage.stock_id.in_(stock_ids),
                FundamentalVintage.available_at <= available_end,
                FundamentalVintage.fiscal_period_end <= end_date,
            )
            .order_by(
                FundamentalVintage.stock_id,
                FundamentalVintage.available_at,
                FundamentalVintage.fiscal_period_end,
                FundamentalVintage.revision_id,
            )
        )
        financials: defaultdict[int, list[FactorFinancialPoint]] = defaultdict(list)
        for item in financial_models:
            try:
                DataTimestamps(
                    event_time=normalize_utc(item.publication_time),
                    available_time=normalize_utc(item.available_at),
                    ingested_time=normalize_utc(item.ingested_at),
                )
            except ValueError as error:
                raise ValueError(
                    "financial point-in-time timestamps are unsafe for "
                    f"stock_id={item.stock_id} period_end={item.fiscal_period_end}: {error}"
                ) from error
            values = item.restated_values if item.is_restatement else item.original_values
            values = values or item.original_values

            financials[item.stock_id].append(
                FactorFinancialPoint(
                    period_end=item.fiscal_period_end,
                    period_type=item.period_type,
                    available_at=item.available_at,
                    revenue=_numeric_value(values, "revenue"),
                    free_cash_flow=_numeric_value(values, "free_cash_flow"),
                    roe=_numeric_value(values, "roe"),
                    roic=_numeric_value(values, "roic"),
                    pe=_numeric_value(values, "pe"),
                    pb=_numeric_value(values, "pb"),
                    ps=_numeric_value(values, "ps"),
                    gross_margin=_numeric_value(values, "gross_margin"),
                    debt_ratio=_numeric_value(values, "debt_ratio"),
                    eps=_numeric_value(values, "diluted_eps")
                    or _numeric_value(values, "eps"),
                    shares_outstanding=_numeric_value(values, "shares_outstanding"),
                    source=item.source,
                    revision_id=item.revision_id,
                    data_version=f"{item.filing_id}:{item.revision_id}",
                )
            )
        return FactorDataset(
            assets=tuple(
                FactorAssetData(
                    instrument=MarketGraphRepository.instrument(stock),
                    prices=tuple(sorted(prices.get(stock.id, []), key=lambda item: item.date)),
                    financials=tuple(financials.get(stock.id, [])),
                )
                for stock in stocks
            )
        )

    def latest_run(self, analysis_type: str) -> FactorResearchRun | None:
        return self.session.scalar(
            select(FactorResearchRun)
            .where(
                FactorResearchRun.analysis_type == analysis_type,
                FactorResearchRun.status == "completed",
            )
            .order_by(FactorResearchRun.created_at.desc(), FactorResearchRun.id.desc())
            .limit(1)
        )

    def scores_for_run(self, run_id: int) -> list[FactorScore]:
        return list(
            self.session.scalars(
                select(FactorScore)
                .where(FactorScore.run_id == run_id)
                .order_by(FactorScore.as_of_date, FactorScore.factor_score.desc())
            )
        )

    def periods_for_run(self, run_id: int) -> list[FactorBacktestPeriod]:
        return list(
            self.session.scalars(
                select(FactorBacktestPeriod)
                .where(FactorBacktestPeriod.run_id == run_id)
                .order_by(FactorBacktestPeriod.rebalance_date)
            )
        )

    def summary_for_run(self, run_id: int) -> FactorBacktestSummary | None:
        return self.session.scalar(
            select(FactorBacktestSummary).where(FactorBacktestSummary.run_id == run_id)
        )

    def instruments_by_ids(self, stock_ids: set[int]) -> dict[int, GraphInstrument]:
        if not stock_ids:
            return {}
        stocks = self.session.scalars(
            select(Stock)
            .options(selectinload(Stock.industry))
            .where(Stock.id.in_(tuple(stock_ids)))
        )
        return {stock.id: MarketGraphRepository.instrument(stock) for stock in stocks}
