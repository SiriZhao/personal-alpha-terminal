from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from personal_alpha_terminal.analysis.market_graph.repository import (
    MarketGraphRepository,
)
from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument
from personal_alpha_terminal.data.market_data.selection import (
    preferred_source,
    select_consistent_price_series,
)
from personal_alpha_terminal.models import (
    FxRate,
    Portfolio,
    PortfolioPosition,
    PortfolioRiskMetric,
    PortfolioRiskRun,
    PortfolioStressResult,
    Price,
    Stock,
)
from personal_alpha_terminal.portfolio.schemas import (
    FxPoint,
    FxSeries,
    PortfolioRiskData,
    RiskPortfolioOption,
    RiskPositionData,
    RiskPricePoint,
)


class PortfolioRiskRepository:
    """Load normalized portfolio inputs and persisted risk snapshots."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_portfolios(self) -> tuple[RiskPortfolioOption, ...]:
        portfolios = self.session.scalars(select(Portfolio).order_by(Portfolio.name))
        return tuple(
            RiskPortfolioOption(
                id=item.id,
                name=item.name,
                base_currency=item.base_currency.upper(),
            )
            for item in portfolios
        )

    def list_benchmarks(self) -> tuple[GraphInstrument, ...]:
        stocks = self.session.scalars(
            select(Stock)
            .options(selectinload(Stock.industry))
            .where(
                Stock.is_active.is_(True),
                Stock.asset_type.in_(("index", "etf")),
            )
            .order_by(Stock.market, Stock.symbol)
        )
        return tuple(MarketGraphRepository.instrument(stock) for stock in stocks)

    def load_data(
        self,
        *,
        portfolio_id: int,
        benchmark_stock_id: int,
        start_date: date,
        end_date: date,
        fx_max_staleness_days: int,
    ) -> PortfolioRiskData:
        portfolio = self.session.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise ValueError("portfolio does not exist")
        as_of_date = self.session.scalar(
            select(func.max(PortfolioPosition.as_of_date)).where(
                PortfolioPosition.portfolio_id == portfolio_id,
                PortfolioPosition.as_of_date <= end_date,
            )
        )
        if as_of_date is None:
            raise ValueError("portfolio has no positions on or before end_date")
        positions = list(
            self.session.scalars(
                select(PortfolioPosition)
                .options(selectinload(PortfolioPosition.stock).selectinload(Stock.industry))
                .where(
                    PortfolioPosition.portfolio_id == portfolio_id,
                    PortfolioPosition.as_of_date == as_of_date,
                )
                .order_by(PortfolioPosition.stock_id)
            )
        )
        if not positions:
            raise ValueError("portfolio has no positions")
        if any(item.quantity < 0 for item in positions):
            raise ValueError("short positions are not supported by the first risk model")
        if any(item.stock.asset_type not in {"stock", "etf"} for item in positions):
            raise ValueError("portfolio positions must be stocks or ETFs")

        benchmark = self.session.scalar(
            select(Stock)
            .options(selectinload(Stock.industry))
            .where(
                Stock.id == benchmark_stock_id,
                Stock.is_active.is_(True),
                Stock.asset_type.in_(("index", "etf")),
            )
        )
        if benchmark is None:
            raise ValueError("benchmark must be an active index or ETF")

        position_ids = tuple(item.stock_id for item in positions)
        price_ids = (*position_ids, benchmark_stock_id)
        price_models = self.session.scalars(
            select(Price)
            .where(
                Price.stock_id.in_(price_ids),
                Price.trade_date >= start_date,
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
        for item in price_models:
            price_rows[item.stock_id].append(item)
        prices: defaultdict[int, list[RiskPricePoint]] = defaultdict(list)
        stock_by_id = {item.stock_id: item.stock for item in positions}
        stock_by_id[benchmark.id] = benchmark
        for stock_id, rows in price_rows.items():
            for item in select_consistent_price_series(
                rows,
                preferred=preferred_source(stock_by_id[stock_id].market),
            ):
                close = float(item.adjusted_close or item.close)
                if close > 0:
                    prices[stock_id].append(RiskPricePoint(date=item.trade_date, close=close))

        base_currency = portfolio.base_currency.upper()
        currencies = {
            item.stock.currency.upper()
            for item in positions
            if item.stock.currency.upper() != base_currency
        }
        if benchmark.currency.upper() != base_currency:
            currencies.add(benchmark.currency.upper())
        fx_series = self._load_fx_series(
            currencies=currencies,
            target_currency=base_currency,
            start_date=start_date - timedelta(days=fx_max_staleness_days),
            end_date=end_date,
        )
        return PortfolioRiskData(
            portfolio_id=portfolio.id,
            portfolio_name=portfolio.name,
            base_currency=base_currency,
            cash_balance=float(portfolio.cash_balance),
            as_of_date=as_of_date,
            positions=tuple(
                RiskPositionData(
                    instrument=MarketGraphRepository.instrument(item.stock),
                    currency=item.stock.currency.upper(),
                    industry=(
                        item.stock.industry.name if item.stock.industry is not None else "未分类"
                    ),
                    quantity=float(item.quantity),
                    prices=tuple(sorted(prices[item.stock_id], key=lambda point: point.date)),
                )
                for item in positions
            ),
            benchmark=MarketGraphRepository.instrument(benchmark),
            benchmark_currency=benchmark.currency.upper(),
            benchmark_prices=tuple(
                sorted(prices[benchmark_stock_id], key=lambda point: point.date)
            ),
            fx_series=fx_series,
        )

    def latest_run(self, portfolio_id: int | None = None) -> PortfolioRiskRun | None:
        statement = select(PortfolioRiskRun).where(PortfolioRiskRun.status == "completed")
        if portfolio_id is not None:
            statement = statement.where(PortfolioRiskRun.portfolio_id == portfolio_id)
        return self.session.scalar(
            statement.order_by(
                PortfolioRiskRun.created_at.desc(),
                PortfolioRiskRun.id.desc(),
            ).limit(1)
        )

    def metric_for_run(self, run_id: int) -> PortfolioRiskMetric | None:
        return self.session.scalar(
            select(PortfolioRiskMetric).where(PortfolioRiskMetric.run_id == run_id)
        )

    def stress_results_for_run(self, run_id: int) -> list[PortfolioStressResult]:
        return list(
            self.session.scalars(
                select(PortfolioStressResult)
                .where(PortfolioStressResult.run_id == run_id)
                .order_by(PortfolioStressResult.id)
            )
        )

    def instruments_by_ids(
        self,
        stock_ids: set[int],
    ) -> dict[int, GraphInstrument]:
        if not stock_ids:
            return {}
        stocks = self.session.scalars(
            select(Stock)
            .options(selectinload(Stock.industry))
            .where(Stock.id.in_(tuple(stock_ids)))
        )
        return {stock.id: MarketGraphRepository.instrument(stock) for stock in stocks}

    def portfolio_option(self, portfolio_id: int) -> RiskPortfolioOption | None:
        item = self.session.get(Portfolio, portfolio_id)
        if item is None:
            return None
        return RiskPortfolioOption(
            id=item.id,
            name=item.name,
            base_currency=item.base_currency.upper(),
        )

    def _load_fx_series(
        self,
        *,
        currencies: set[str],
        target_currency: str,
        start_date: date,
        end_date: date,
    ) -> tuple[FxSeries, ...]:
        if not currencies:
            return ()
        pair_predicates = [
            or_(
                and_(
                    FxRate.base_currency == currency,
                    FxRate.quote_currency == target_currency,
                ),
                and_(
                    FxRate.base_currency == target_currency,
                    FxRate.quote_currency == currency,
                ),
            )
            for currency in sorted(currencies)
        ]
        models = self.session.scalars(
            select(FxRate)
            .where(
                or_(*pair_predicates),
                FxRate.rate_date >= start_date,
                FxRate.rate_date <= end_date,
            )
            .order_by(
                FxRate.base_currency,
                FxRate.quote_currency,
                FxRate.rate_date,
                FxRate.source,
            )
        )
        distinct: dict[tuple[str, str, date], FxRate] = {}
        for item in models:
            distinct.setdefault(
                (item.base_currency, item.quote_currency, item.rate_date),
                item,
            )
        grouped: defaultdict[tuple[str, str], list[FxPoint]] = defaultdict(list)
        for (base, quote, _), item in distinct.items():
            grouped[(base, quote)].append(FxPoint(date=item.rate_date, rate=float(item.rate)))
        return tuple(
            FxSeries(
                base_currency=base,
                quote_currency=quote,
                values=tuple(sorted(values, key=lambda point: point.date)),
            )
            for (base, quote), values in sorted(grouped.items())
        )
