from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from personal_alpha_terminal.data.market_data.selection import (
    preferred_source,
    select_consistent_price_series,
)
from personal_alpha_terminal.models import (
    FxRate,
    Portfolio,
    PortfolioAllocationTarget,
    PortfolioPosition,
    PortfolioTransaction,
    Price,
    Stock,
)
from personal_alpha_terminal.portfolio.management_schemas import (
    AllocationTarget,
    AssetPricePoint,
    AssetPriceSeries,
    LedgerEvent,
    ManagedAsset,
    PortfolioManagementData,
    TransactionDraft,
)
from personal_alpha_terminal.portfolio.schemas import FxPoint, FxSeries


class PortfolioManagementRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_transaction(
        self,
        *,
        portfolio_id: int,
        draft: TransactionDraft,
    ) -> PortfolioTransaction:
        if self.session.get(Portfolio, portfolio_id) is None:
            raise ValueError("portfolio does not exist")
        if draft.stock_id is not None and self.session.get(Stock, draft.stock_id) is None:
            raise ValueError("asset does not exist")
        if draft.external_id:
            existing = self.session.scalar(
                select(PortfolioTransaction).where(
                    PortfolioTransaction.portfolio_id == portfolio_id,
                    PortfolioTransaction.source == draft.source,
                    PortfolioTransaction.external_id == draft.external_id,
                )
            )
            if existing is not None:
                if not self._matches_draft(existing, draft):
                    raise ValueError(
                        "external transaction id already exists with different payload"
                    )
                return existing
        model = PortfolioTransaction(
            portfolio_id=portfolio_id,
            stock_id=draft.stock_id,
            transaction_type=draft.transaction_type,
            trade_date=draft.trade_date,
            settlement_date=draft.settlement_date,
            quantity=(Decimal(str(draft.quantity)) if draft.quantity is not None else None),
            unit_price=(Decimal(str(draft.unit_price)) if draft.unit_price is not None else None),
            cash_amount=(
                Decimal(str(draft.cash_amount)) if draft.cash_amount is not None else None
            ),
            fee_amount=Decimal(str(draft.fee_amount)),
            currency=draft.currency.upper(),
            fx_rate_to_base=Decimal(str(draft.fx_rate_to_base)),
            source=draft.source,
            external_id=draft.external_id,
            notes=draft.notes,
            event_time=draft.event_time,
            available_time=draft.available_time,
        )
        self.session.add(model)
        self.session.flush()
        return model

    def transaction_by_external_id(
        self,
        *,
        portfolio_id: int,
        source: str,
        external_id: str,
    ) -> PortfolioTransaction | None:
        return self.session.scalar(
            select(PortfolioTransaction).where(
                PortfolioTransaction.portfolio_id == portfolio_id,
                PortfolioTransaction.source == source,
                PortfolioTransaction.external_id == external_id,
            )
        )

    def apply_trade_to_current_snapshot(
        self,
        *,
        portfolio_id: int,
        stock_id: int,
        as_of_date: date,
        transaction_type: str,
        quantity: Decimal,
        unit_price: Decimal,
        fee_amount: Decimal,
        currency: str,
    ) -> None:
        """Atomically synchronize a manually confirmed fill to current holdings.

        The immutable transaction remains the performance source of truth. This
        snapshot and cash balance are the operational current-state projection
        shown by Today/Doctor. Backdated fills behind a newer imported snapshot
        are rejected rather than silently rewriting current holdings.
        """

        portfolio = self.session.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise ValueError("portfolio does not exist")
        if currency.upper() != portfolio.base_currency.upper():
            raise ValueError("manual fill currency requires an explicit FX conversion")
        if transaction_type not in {"buy", "sell"}:
            raise ValueError("only buy/sell fills can update a position snapshot")
        if min(quantity, unit_price) <= 0 or fee_amount < 0:
            raise ValueError("manual fill snapshot values are invalid")

        latest_date = self.session.scalar(
            select(func.max(PortfolioPosition.as_of_date)).where(
                PortfolioPosition.portfolio_id == portfolio_id
            )
        )
        if latest_date is not None and latest_date > as_of_date:
            raise ValueError("manual fill predates the current portfolio snapshot")
        if latest_date is not None and latest_date < as_of_date:
            previous = tuple(
                self.session.scalars(
                    select(PortfolioPosition).where(
                        PortfolioPosition.portfolio_id == portfolio_id,
                        PortfolioPosition.as_of_date == latest_date,
                    )
                )
            )
            self.session.add_all(
                PortfolioPosition(
                    portfolio_id=portfolio_id,
                    stock_id=item.stock_id,
                    as_of_date=as_of_date,
                    quantity=item.quantity,
                    average_cost=item.average_cost,
                )
                for item in previous
            )
            self.session.flush()

        position = self.session.scalar(
            select(PortfolioPosition).where(
                PortfolioPosition.portfolio_id == portfolio_id,
                PortfolioPosition.stock_id == stock_id,
                PortfolioPosition.as_of_date == as_of_date,
            )
        )
        gross = quantity * unit_price
        if transaction_type == "buy":
            cash_required = gross + fee_amount
            if portfolio.cash_balance < cash_required:
                raise ValueError("manual buy exceeds the recorded portfolio cash balance")
            prior_quantity = position.quantity if position is not None else Decimal("0")
            prior_cost = (
                prior_quantity * position.average_cost
                if position is not None and position.average_cost is not None
                else Decimal("0")
            )
            new_quantity = prior_quantity + quantity
            average_cost = (prior_cost + gross + fee_amount) / new_quantity
            if position is None:
                self.session.add(
                    PortfolioPosition(
                        portfolio_id=portfolio_id,
                        stock_id=stock_id,
                        as_of_date=as_of_date,
                        quantity=new_quantity,
                        average_cost=average_cost,
                    )
                )
            else:
                position.quantity = new_quantity
                position.average_cost = average_cost
            portfolio.cash_balance -= cash_required
        else:
            if position is None or position.quantity < quantity:
                raise ValueError("manual sell exceeds the recorded position quantity")
            remaining = position.quantity - quantity
            portfolio.cash_balance += gross - fee_amount
            if remaining == 0:
                self.session.delete(position)
            else:
                position.quantity = remaining
        self.session.flush()

    @staticmethod
    def _matches_draft(model: PortfolioTransaction, draft: TransactionDraft) -> bool:
        def decimal(value: float | None) -> Decimal | None:
            return Decimal(str(value)) if value is not None else None

        def normalized(value: datetime) -> datetime:
            if value.tzinfo is None:
                return value
            return value.astimezone(UTC).replace(tzinfo=None)

        return (
            model.stock_id == draft.stock_id
            and model.transaction_type == draft.transaction_type
            and model.trade_date == draft.trade_date
            and model.settlement_date == draft.settlement_date
            and model.quantity == decimal(draft.quantity)
            and model.unit_price == decimal(draft.unit_price)
            and model.cash_amount == decimal(draft.cash_amount)
            and model.fee_amount == Decimal(str(draft.fee_amount))
            and model.currency == draft.currency.upper()
            and model.fx_rate_to_base == Decimal(str(draft.fx_rate_to_base))
            and normalized(model.event_time) == normalized(draft.event_time)
            and normalized(model.available_time) == normalized(draft.available_time)
        )

    def replace_targets(
        self,
        *,
        portfolio_id: int,
        effective_date: date,
        targets: tuple[tuple[int | None, str | None, float, str | None], ...],
    ) -> None:
        existing = self.session.scalars(
            select(PortfolioAllocationTarget).where(
                PortfolioAllocationTarget.portfolio_id == portfolio_id,
                PortfolioAllocationTarget.effective_date == effective_date,
            )
        )
        for item in existing:
            self.session.delete(item)
        for stock_id, cash_currency, weight, rationale in targets:
            self.session.add(
                PortfolioAllocationTarget(
                    portfolio_id=portfolio_id,
                    stock_id=stock_id,
                    cash_currency=(cash_currency.upper() if cash_currency else None),
                    effective_date=effective_date,
                    target_weight=Decimal(str(weight)),
                    rationale=rationale,
                )
            )
        self.session.flush()

    def load_data(
        self,
        *,
        portfolio_id: int,
        benchmark_stock_id: int,
        start_date: date,
        end_date: date,
        price_max_staleness_days: int,
        fx_max_staleness_days: int,
    ) -> PortfolioManagementData:
        portfolio = self.session.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise ValueError("portfolio does not exist")
        benchmark = self.session.scalar(
            select(Stock)
            .options(selectinload(Stock.industry))
            .where(
                Stock.id == benchmark_stock_id,
                Stock.asset_type.in_(("index", "etf")),
            )
        )
        if benchmark is None:
            raise ValueError("benchmark must be an index or ETF")
        cutoff = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
        transactions = tuple(
            self.session.scalars(
                select(PortfolioTransaction)
                .options(
                    selectinload(PortfolioTransaction.stock).selectinload(Stock.industry)
                )
                .where(
                    PortfolioTransaction.portfolio_id == portfolio_id,
                    PortfolioTransaction.trade_date <= end_date,
                    PortfolioTransaction.available_time < cutoff,
                )
                .order_by(PortfolioTransaction.trade_date, PortfolioTransaction.id)
            )
        )
        if not transactions:
            raise ValueError("portfolio has no available transaction ledger")
        stock_ids = {
            item.stock_id for item in transactions if item.stock_id is not None
        }
        price_ids = (*sorted(stock_ids), benchmark_stock_id)
        buffer_start = start_date - timedelta(
            days=max(price_max_staleness_days, fx_max_staleness_days)
        )
        rows = self.session.scalars(
            select(Price)
            .where(
                Price.stock_id.in_(price_ids),
                Price.trade_date >= buffer_start,
                Price.trade_date <= end_date,
                Price.available_time.is_not(None),
                Price.available_time < cutoff,
            )
            .order_by(
                Price.stock_id,
                Price.trade_date,
                Price.ingested_at.desc(),
                Price.source,
            )
        )
        rows_by_stock: defaultdict[int, list[Price]] = defaultdict(list)
        for row in rows:
            rows_by_stock[row.stock_id].append(row)
        stocks = {
            item.stock_id: item.stock
            for item in transactions
            if item.stock_id is not None and item.stock is not None
        }
        stocks[benchmark.id] = benchmark
        selected: dict[int, tuple[AssetPricePoint, ...]] = {}
        for stock_id, price_rows in rows_by_stock.items():
            selected[stock_id] = tuple(
                AssetPricePoint(date=item.trade_date, close=float(item.close))
                for item in select_consistent_price_series(
                    price_rows,
                    preferred=preferred_source(stocks[stock_id].market),
                )
                if item.close > 0
            )
        base_currency = portfolio.base_currency.upper()
        currencies = {item.currency.upper() for item in transactions}
        currencies.update(item.currency.upper() for item in stocks.values())
        currencies.discard(base_currency)
        return PortfolioManagementData(
            portfolio_id=portfolio.id,
            portfolio_name=portfolio.name,
            base_currency=base_currency,
            start_date=start_date,
            end_date=end_date,
            transactions=tuple(self._ledger_event(item) for item in transactions),
            prices=tuple(
                AssetPriceSeries(
                    asset=self._asset(stocks[stock_id]),
                    values=selected.get(stock_id, ()),
                )
                for stock_id in sorted(stock_ids)
            ),
            fx_series=self._load_fx_series(
                currencies=currencies,
                target_currency=base_currency,
                start_date=buffer_start,
                end_date=end_date,
            ),
            benchmark=self._asset(benchmark),
            benchmark_prices=selected.get(benchmark.id, ()),
            targets=self._load_targets(portfolio.id, end_date),
        )

    def _load_targets(
        self,
        portfolio_id: int,
        as_of_date: date,
    ) -> tuple[AllocationTarget, ...]:
        effective_date = self.session.scalar(
            select(func.max(PortfolioAllocationTarget.effective_date)).where(
                PortfolioAllocationTarget.portfolio_id == portfolio_id,
                PortfolioAllocationTarget.effective_date <= as_of_date,
            )
        )
        if effective_date is None:
            return ()
        rows = self.session.scalars(
            select(PortfolioAllocationTarget)
            .options(selectinload(PortfolioAllocationTarget.stock))
            .where(
                PortfolioAllocationTarget.portfolio_id == portfolio_id,
                PortfolioAllocationTarget.effective_date == effective_date,
            )
            .order_by(PortfolioAllocationTarget.id)
        )
        return tuple(
            AllocationTarget(
                key=(
                    f"asset:{item.stock_id}"
                    if item.stock_id is not None
                    else f"cash:{item.cash_currency}"
                ),
                label=(
                    item.stock.symbol
                    if item.stock is not None
                    else f"Cash {item.cash_currency}"
                ),
                target_weight=float(item.target_weight),
            )
            for item in rows
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
        rows = self.session.scalars(
            select(FxRate)
            .where(
                FxRate.rate_date >= start_date,
                FxRate.rate_date <= end_date,
                or_(
                    and_(
                        FxRate.base_currency.in_(currencies),
                        FxRate.quote_currency == target_currency,
                    ),
                    and_(
                        FxRate.base_currency == target_currency,
                        FxRate.quote_currency.in_(currencies),
                    ),
                ),
            )
            .order_by(FxRate.base_currency, FxRate.quote_currency, FxRate.rate_date)
        )
        grouped: defaultdict[tuple[str, str], dict[date, FxPoint]] = defaultdict(dict)
        for item in rows:
            grouped[(item.base_currency, item.quote_currency)][item.rate_date] = FxPoint(
                date=item.rate_date,
                rate=float(item.rate),
            )
        return tuple(
            FxSeries(
                base_currency=pair[0],
                quote_currency=pair[1],
                values=tuple(points[key] for key in sorted(points)),
            )
            for pair, points in sorted(grouped.items())
        )

    @staticmethod
    def _asset(stock: Stock) -> ManagedAsset:
        return ManagedAsset(
            id=stock.id,
            symbol=stock.symbol,
            name=stock.name,
            asset_class=stock.asset_type,
            currency=stock.currency.upper(),
            industry=stock.industry.name if stock.industry is not None else "Unclassified",
        )

    @classmethod
    def _ledger_event(cls, item: PortfolioTransaction) -> LedgerEvent:
        return LedgerEvent(
            id=item.id,
            transaction_type=item.transaction_type,
            trade_date=item.trade_date,
            settlement_date=item.settlement_date,
            currency=item.currency.upper(),
            fx_rate_to_base=float(item.fx_rate_to_base),
            available_time=item.available_time,
            asset=cls._asset(item.stock) if item.stock is not None else None,
            quantity=float(item.quantity) if item.quantity is not None else None,
            unit_price=float(item.unit_price) if item.unit_price is not None else None,
            cash_amount=float(item.cash_amount) if item.cash_amount is not None else None,
            fee_amount=float(item.fee_amount),
        )
