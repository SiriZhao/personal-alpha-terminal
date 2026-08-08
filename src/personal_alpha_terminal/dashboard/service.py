from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.dashboard.repository import DashboardRepository
from personal_alpha_terminal.dashboard.schemas import (
    CurrencyTotal,
    InstrumentOption,
    MarketIndexSnapshot,
    PortfolioOption,
    PortfolioRiskView,
    PortfolioSnapshot,
    PositionView,
    PricePoint,
    StockDetail,
)
from personal_alpha_terminal.data.market_data.selection import (
    preferred_source,
    select_consistent_price_series,
)
from personal_alpha_terminal.models import Price, Stock
from personal_alpha_terminal.portfolio.risk import calculate_portfolio_risk


class DashboardService:
    """Read-only use cases consumed by Streamlit and future presentation layers."""

    def __init__(self, repository: DashboardRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    def market_overview(self) -> tuple[MarketIndexSnapshot, ...]:
        indices = self._repository.list_stocks(asset_type="index")
        configured_order = {
            key: position for position, key in enumerate(self._configured_index_keys())
        }
        indices.sort(
            key=lambda stock: (
                configured_order.get((stock.market, stock.symbol), 10_000),
                stock.market,
                stock.symbol,
            )
        )

        snapshots: list[MarketIndexSnapshot] = []
        for stock in indices[:8]:
            prices = self._distinct_prices(
                self._repository.get_prices(stock.id, descending=True, limit=30),
                market=stock.market,
            )
            if not prices:
                continue
            latest = prices[-1]
            previous = prices[-2] if len(prices) > 1 else None
            change_pct = (
                float(latest.close / previous.close - 1)
                if previous is not None and previous.close != 0
                else None
            )
            snapshots.append(
                MarketIndexSnapshot(
                    instrument=self._instrument(stock),
                    date=latest.trade_date,
                    close=latest.close,
                    change_pct=change_pct,
                    volume=latest.volume,
                    currency=stock.currency,
                    source=latest.source,
                )
            )
        return tuple(snapshots)

    def list_stock_options(self) -> tuple[InstrumentOption, ...]:
        return tuple(
            self._instrument(stock)
            for stock in self._repository.list_stocks()
            if stock.asset_type in {"stock", "etf"}
        )

    def stock_detail(
        self,
        stock_id: int,
        *,
        start_date: date,
        end_date: date,
    ) -> StockDetail | None:
        stock = self._repository.get_stock(stock_id)
        if stock is None:
            return None
        prices = self._distinct_prices(
            self._repository.get_prices(
                stock_id,
                start_date=start_date,
                end_date=end_date,
            ),
            market=stock.market,
        )
        return StockDetail(
            instrument=self._instrument(stock),
            exchange=stock.exchange,
            currency=stock.currency,
            industry=stock.industry.name if stock.industry else None,
            list_date=stock.list_date,
            is_active=stock.is_active,
            prices=tuple(self._price_point(price) for price in prices),
        )

    def default_stock_start_date(self) -> date:
        return date.today() - timedelta(days=self._settings.dashboard_default_history_days)

    def list_portfolios(self) -> tuple[PortfolioOption, ...]:
        return tuple(
            PortfolioOption(
                id=portfolio.id,
                name=portfolio.name,
                base_currency=portfolio.base_currency,
            )
            for portfolio in self._repository.list_portfolios()
        )

    def portfolio_snapshot(self, portfolio_id: int) -> PortfolioSnapshot | None:
        portfolio = self._repository.get_portfolio(portfolio_id)
        if portfolio is None:
            return None
        option = PortfolioOption(
            id=portfolio.id,
            name=portfolio.name,
            base_currency=portfolio.base_currency,
        )
        as_of_date, positions = self._repository.get_latest_positions(portfolio_id)
        draft_positions: list[PositionView] = []
        currency_totals: defaultdict[str, Decimal] = defaultdict(Decimal)
        currency_totals[portfolio.base_currency] += portfolio.cash_balance
        valuation_complete = True

        for position in positions:
            recent = self._distinct_prices(
                self._repository.get_prices(
                    position.stock_id,
                    end_date=as_of_date,
                    descending=True,
                    limit=15,
                ),
                market=position.stock.market,
            )
            latest = recent[-1] if recent else None
            market_value = position.quantity * latest.close if latest else None
            unrealized_pnl = (
                position.quantity * (latest.close - position.average_cost)
                if latest and position.average_cost is not None
                else None
            )
            if market_value is None:
                valuation_complete = False
            else:
                currency_totals[position.stock.currency] += market_value
            if position.stock.currency != portfolio.base_currency:
                valuation_complete = False
            draft_positions.append(
                PositionView(
                    stock_id=position.stock_id,
                    symbol=position.stock.symbol,
                    name=position.stock.name,
                    market=position.stock.market,
                    industry=position.stock.industry.name if position.stock.industry else None,
                    currency=position.stock.currency,
                    quantity=position.quantity,
                    average_cost=position.average_cost,
                    last_price=latest.close if latest else None,
                    price_date=latest.trade_date if latest else None,
                    market_value=market_value,
                    unrealized_pnl=unrealized_pnl,
                    weight=None,
                )
            )

        invested_value = (
            sum(
                (position.market_value or Decimal("0") for position in draft_positions),
                Decimal("0"),
            )
            if valuation_complete
            else None
        )
        total_value = (
            portfolio.cash_balance + invested_value if invested_value is not None else None
        )
        weighted_positions = tuple(
            PositionView(
                stock_id=position.stock_id,
                symbol=position.symbol,
                name=position.name,
                market=position.market,
                industry=position.industry,
                currency=position.currency,
                quantity=position.quantity,
                average_cost=position.average_cost,
                last_price=position.last_price,
                price_date=position.price_date,
                market_value=position.market_value,
                unrealized_pnl=position.unrealized_pnl,
                weight=(
                    float(position.market_value / total_value)
                    if total_value and position.market_value is not None
                    else None
                ),
            )
            for position in draft_positions
        )
        return PortfolioSnapshot(
            portfolio=option,
            description=portfolio.description,
            as_of_date=as_of_date,
            cash_balance=portfolio.cash_balance,
            total_value=total_value,
            invested_value=invested_value,
            valuation_complete=valuation_complete,
            positions=weighted_positions,
            currency_totals=tuple(
                CurrencyTotal(currency=currency, amount=amount)
                for currency, amount in sorted(currency_totals.items())
            ),
        )

    def portfolio_risk(
        self,
        portfolio_id: int,
        *,
        start_date: date,
        end_date: date,
    ) -> PortfolioRiskView | None:
        snapshot = self.portfolio_snapshot(portfolio_id)
        if snapshot is None:
            return None
        if not snapshot.valuation_complete or snapshot.total_value is None:
            return PortfolioRiskView(
                portfolio=snapshot.portfolio,
                available=False,
                reason="存在非基准币种或缺失行情；接入汇率数据后才能计算组合风险。",
                metrics=None,
            )

        weights = {
            position.stock_id: position.weight
            for position in snapshot.positions
            if position.weight is not None
        }
        histories: dict[int, tuple[tuple[date, float], ...]] = {}
        markets: dict[int, str] = {}
        industries: dict[int, str] = {}
        for position in snapshot.positions:
            prices = self._distinct_prices(
                self._repository.get_prices(
                    position.stock_id,
                    start_date=start_date,
                    end_date=end_date,
                ),
                market=position.market,
            )
            histories[position.stock_id] = tuple(
                (price.trade_date, float(price.adjusted_close or price.close)) for price in prices
            )
            markets[position.stock_id] = position.market
            industries[position.stock_id] = position.industry or "未分类"

        return calculate_portfolio_risk(
            portfolio=snapshot.portfolio,
            weights=weights,
            histories=histories,
            markets=markets,
            industries=industries,
            annual_risk_free_rate=self._settings.dashboard_annual_risk_free_rate,
        )

    def _configured_index_keys(self) -> tuple[tuple[str, str], ...]:
        keys: list[tuple[str, str]] = []
        for item in self._settings.dashboard_major_indices.split(","):
            market, separator, symbol = item.strip().partition(":")
            if separator and market and symbol:
                keys.append((market, symbol))
        return tuple(keys)

    @staticmethod
    def _distinct_prices(prices: list[Price], *, market: str) -> list[Price]:
        return select_consistent_price_series(
            prices,
            preferred=preferred_source(market),
        )

    @staticmethod
    def _instrument(stock: Stock) -> InstrumentOption:
        return InstrumentOption(
            id=stock.id,
            symbol=stock.symbol,
            name=stock.name,
            market=stock.market,
        )

    @staticmethod
    def _price_point(price: Price) -> PricePoint:
        return PricePoint(
            date=price.trade_date,
            open=price.open,
            high=price.high,
            low=price.low,
            close=price.adjusted_close or price.close,
            volume=price.volume,
            source=price.source,
        )
