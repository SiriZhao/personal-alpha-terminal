"""ROUND 6: live portfolio lifecycle, fill gates, PnL, attribution and reconciliation.

Strict lifecycle contract:

    Recommendation -> User Decision -> Order Intent -> Broker Fill -> Position

User acceptance never equals a broker fill.  Pure deterministic helpers plus a
session-backed ledger service compute PnL, NAV, daily attribution and
corporate-action reconciliation state.  Nothing here ever contacts a broker or
auto-executes.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.models import (
    CorporateAction,
    Portfolio,
    PortfolioPosition,
    PortfolioTransaction,
    Price,
    Stock,
)

if TYPE_CHECKING:
    from personal_alpha_terminal.models import QuantDecisionRecommendation


class LifecycleStage(StrEnum):
    RECOMMENDATION = "RECOMMENDATION"
    USER_DECISION = "USER_DECISION"
    ORDER_INTENT = "ORDER_INTENT"
    BROKER_FILL = "BROKER_FILL"
    PORTFOLIO_POSITION = "PORTFOLIO_POSITION"


def semantic_action(
    action: str,
    *,
    current_weight: float,
    target_weight: float,
) -> str:
    """Derive the user-facing action from a stored recommendation action.

    ``SELL`` of a full position is ``EXIT``; ``NO_ACTION`` means no recommendation
    exists.  ``BUY`` / ``ADD`` / ``REDUCE`` / ``HOLD`` pass through.
    """
    normalized = action.upper()
    if normalized == "SELL" and current_weight > 0 and target_weight <= 0:
        return "EXIT"
    if normalized in {"BUY", "ADD", "REDUCE", "HOLD", "SELL"}:
        return normalized
    return "NO_ACTION"


class FillGateDecision(StrEnum):
    ALLOWED = "ALLOWED"
    BLOCKED_EXPIRED = "BLOCKED_EXPIRED"
    BLOCKED_STALE = "BLOCKED_STALE"
    ALLOWED_WITH_OVERRIDE = "ALLOWED_WITH_OVERRIDE"


@dataclass(frozen=True, slots=True)
class FillGate:
    decision: FillGateDecision
    reason: str
    override_required: bool = False


def evaluate_fill_gate(
    recommendation: QuantDecisionRecommendation,
    *,
    executed_at: datetime,
    latest_approved_run_id: int | None = None,
    override_provenance: str | None = None,
) -> FillGate:
    """Fail-closed gate before a manual broker fill touches the real ledger.

    - Fill after ``expires_at`` is blocked unless an explicit manual-override
      provenance is supplied.
    - Fill from a run that is no longer the latest approved run is stale and
      requires an explicit override provenance.
    """
    if executed_at.tzinfo is None:
        raise ValueError("fill timestamp must be timezone-aware")
    utc_at = executed_at.astimezone(UTC)
    expired = utc_at > _aware(recommendation.expires_at)
    stale = latest_approved_run_id is not None and recommendation.run_id != latest_approved_run_id
    override = (override_provenance or "").strip()
    if not expired and not stale:
        return FillGate(FillGateDecision.ALLOWED, "fill within validity and latest run")
    reasons: list[str] = []
    if expired:
        reasons.append(f"recommendation expired at {recommendation.expires_at.isoformat()}")
    if stale:
        reasons.append(
            f"recommendation run {recommendation.run_id} is not the latest "
            f"approved run {latest_approved_run_id}"
        )
    if override:
        return FillGate(
            FillGateDecision.ALLOWED_WITH_OVERRIDE,
            "; ".join(reasons) + f"; manual override provenance: {override}",
            override_required=True,
        )
    primary = FillGateDecision.BLOCKED_EXPIRED if expired else FillGateDecision.BLOCKED_STALE
    return FillGate(primary, "; ".join(reasons), override_required=True)


@dataclass(frozen=True, slots=True)
class PositionPnL:
    symbol: str
    quantity: float
    average_cost: float | None
    market_price: float | None
    cost_basis: float | None
    market_value: float
    unrealized_pnl: float | None
    weight: float


@dataclass(frozen=True, slots=True)
class PortfolioPnL:
    nav: float
    cash: float
    total_cost_basis: float | None
    total_market_value: float
    unrealized_pnl: float | None
    realized_pnl: float | None
    positions: tuple[PositionPnL, ...]

    def document(self) -> dict[str, object]:
        return {
            "nav": self.nav,
            "cash": self.cash,
            "total_cost_basis": self.total_cost_basis,
            "total_market_value": self.total_market_value,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "positions": [
                {
                    "symbol": item.symbol,
                    "quantity": item.quantity,
                    "average_cost": item.average_cost,
                    "market_price": item.market_price,
                    "cost_basis": item.cost_basis,
                    "market_value": item.market_value,
                    "unrealized_pnl": item.unrealized_pnl,
                    "weight": item.weight,
                }
                for item in self.positions
            ],
        }


@dataclass(frozen=True, slots=True)
class DailyAttribution:
    beginning_nav: float | None
    ending_nav: float
    external_flow: float
    realized_pnl: float | None
    unrealized_pnl: float | None
    fees: float
    total_pnl: float | None
    trading_pnl: float | None
    market_pnl: float | None
    benchmark_return: float | None
    portfolio_return: float | None
    active_return: float | None

    def document(self) -> dict[str, object]:
        return {
            "beginning_nav": self.beginning_nav,
            "ending_nav": self.ending_nav,
            "external_flow": self.external_flow,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "fees": self.fees,
            "total_pnl": self.total_pnl,
            "trading_pnl": self.trading_pnl,
            "market_pnl": self.market_pnl,
            "benchmark_return": self.benchmark_return,
            "portfolio_return": self.portfolio_return,
            "active_return": self.active_return,
        }


@dataclass(frozen=True, slots=True)
class PositionReconciliation:
    symbol: str
    stock_id: int
    status: str  # OK or RECONCILIATION_REQUIRED
    actions: tuple[dict[str, object], ...]

    def document(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "stock_id": self.stock_id,
            "status": self.status,
            "actions": list(self.actions),
        }


class PortfolioLifecycleService:
    """Session-backed ledger analysis for the live portfolio lifecycle."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def latest_positions(
        self, portfolio_id: int, *, as_of: datetime
    ) -> tuple[PortfolioPosition, ...]:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        latest_dates = (
            select(
                PortfolioPosition.stock_id,
                func.max(PortfolioPosition.as_of_date).label("latest_date"),
            )
            .where(
                PortfolioPosition.portfolio_id == portfolio_id,
                PortfolioPosition.as_of_date <= as_of.date(),
            )
            .group_by(PortfolioPosition.stock_id)
            .subquery()
        )
        return tuple(
            self.session.scalars(
                select(PortfolioPosition)
                .join(
                    latest_dates,
                    (PortfolioPosition.stock_id == latest_dates.c.stock_id)
                    & (PortfolioPosition.as_of_date == latest_dates.c.latest_date),
                )
                .where(PortfolioPosition.portfolio_id == portfolio_id)
            )
        )

    def market_price(self, stock_id: int, *, as_of: datetime) -> Decimal | None:
        price = self.session.scalar(
            select(Price)
            .where(
                Price.stock_id == stock_id,
                Price.trade_date <= as_of.date(),
                Price.available_time.is_not(None),
                Price.available_time <= as_of,
                Price.price_type == "unadjusted_ohlcv",
            )
            .order_by(Price.trade_date.desc(), Price.id.desc())
            .limit(1)
        )
        return Decimal(str(price.close)) if price is not None else None

    def portfolio_pnl(self, portfolio_id: int, *, as_of: datetime) -> PortfolioPnL:
        portfolio = self.session.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise ValueError("portfolio does not exist")
        cash = portfolio.cash_balance or Decimal("0")
        positions = self.latest_positions(portfolio_id, as_of=as_of)
        rows: list[PositionPnL] = []
        total_market = Decimal("0")
        total_cost = Decimal("0")
        has_cost = False
        for position in positions:
            stock = self.session.get(Stock, position.stock_id)
            symbol = stock.symbol if stock is not None else str(position.stock_id)
            price = self.market_price(position.stock_id, as_of=as_of)
            quantity = position.quantity or Decimal("0")
            market_value = quantity * (price or Decimal("0"))
            total_market += market_value
            if position.average_cost is not None:
                total_cost += quantity * position.average_cost
                has_cost = True
            rows.append(
                PositionPnL(
                    symbol=symbol,
                    quantity=float(quantity),
                    average_cost=(
                        float(position.average_cost)
                        if position.average_cost is not None
                        else None
                    ),
                    market_price=float(price) if price is not None else None,
                    cost_basis=(
                        float(quantity * position.average_cost)
                        if position.average_cost is not None
                        else None
                    ),
                    market_value=float(market_value),
                    unrealized_pnl=(
                        float(market_value - quantity * position.average_cost)
                        if position.average_cost is not None
                        else None
                    ),
                    weight=0.0,
                )
            )
        nav = float(cash + total_market)
        weighted = tuple(
            PositionPnL(
                item.symbol,
                item.quantity,
                item.average_cost,
                item.market_price,
                item.cost_basis,
                item.market_value,
                item.unrealized_pnl,
                (item.market_value / nav if nav > 0 else 0.0),
            )
            for item in rows
        )
        realized = self.realized_pnl(portfolio_id, as_of=as_of)
        return PortfolioPnL(
            nav=nav,
            cash=float(cash),
            total_cost_basis=(float(total_cost) if has_cost else None),
            total_market_value=float(total_market),
            unrealized_pnl=(float(total_market - total_cost) if has_cost else None),
            realized_pnl=realized,
            positions=weighted,
        )

    def realized_pnl(self, portfolio_id: int, *, as_of: datetime) -> float | None:
        """Average-cost realized P&L from the immutable sell ledger.

        For each buy we add quantity and gross cost + fee; for each sell we
        allocate cost at the running average unit cost and book
        ``proceeds - allocated cost`` (proceeds = qty * price - fee).
        """
        transactions = tuple(
            self.session.scalars(
                select(PortfolioTransaction)
                .where(
                    PortfolioTransaction.portfolio_id == portfolio_id,
                    PortfolioTransaction.trade_date <= as_of.date(),
                )
                .order_by(PortfolioTransaction.trade_date, PortfolioTransaction.id)
            )
        )
        if not transactions:
            return None
        quantity_by_stock: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        cost_by_stock: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        total_realized = Decimal("0")
        any_sell = False
        for transaction in transactions:
            if transaction.stock_id is None or transaction.quantity is None:
                continue
            stock_id = transaction.stock_id
            qty = transaction.quantity
            if transaction.transaction_type == "buy":
                quantity_by_stock[stock_id] += qty
                cost_by_stock[stock_id] += (
                    qty * (transaction.unit_price or Decimal("0"))
                    + transaction.fee_amount
                )
            elif transaction.transaction_type == "sell":
                any_sell = True
                prior_qty = quantity_by_stock[stock_id]
                avg_unit = (
                    cost_by_stock[stock_id] / prior_qty
                    if prior_qty > 0
                    else Decimal("0")
                )
                allocated = qty * avg_unit
                proceeds = qty * (transaction.unit_price or Decimal("0")) - transaction.fee_amount
                total_realized += proceeds - allocated
                quantity_by_stock[stock_id] = prior_qty - qty
                cost_by_stock[stock_id] -= allocated
        return float(total_realized) if any_sell else None

    def daily_attribution(
        self,
        portfolio_id: int,
        *,
        as_of: datetime,
        previous_as_of: datetime | None = None,
        benchmark_return: float | None = None,
    ) -> DailyAttribution:
        portfolio = self.session.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise ValueError("portfolio does not exist")
        ending = self.portfolio_pnl(portfolio_id, as_of=as_of)
        beginning = (
            self.portfolio_pnl(portfolio_id, as_of=previous_as_of)
            if previous_as_of is not None
            else None
        )
        external_flow = self._external_flow(
            portfolio_id, start=previous_as_of, end=as_of
        )
        total_pnl = (
            ending.nav - (beginning.nav if beginning is not None else 0.0) - external_flow
        )
        fees = self._fees(portfolio_id, start=previous_as_of, end=as_of)
        realized_now = ending.realized_pnl or 0.0
        realized_before = (beginning.realized_pnl or 0.0) if beginning is not None else 0.0
        trading_pnl = (realized_now - realized_before) - fees
        market_pnl = total_pnl - trading_pnl
        portfolio_return = (
            total_pnl / beginning.nav if beginning is not None and beginning.nav > 0 else None
        )
        active_return = (
            portfolio_return - benchmark_return
            if portfolio_return is not None and benchmark_return is not None
            else None
        )
        return DailyAttribution(
            beginning_nav=(beginning.nav if beginning is not None else None),
            ending_nav=ending.nav,
            external_flow=external_flow,
            realized_pnl=ending.realized_pnl,
            unrealized_pnl=ending.unrealized_pnl,
            fees=fees,
            total_pnl=total_pnl,
            trading_pnl=trading_pnl,
            market_pnl=market_pnl,
            benchmark_return=benchmark_return,
            portfolio_return=portfolio_return,
            active_return=active_return,
        )

    def corporate_action_reconciliation(
        self, portfolio_id: int, *, as_of: datetime
    ) -> tuple[PositionReconciliation, ...]:
        """Flag held positions affected by unreconciled corporate actions.

        Corporate actions are never auto-applied.  If a split, dividend, symbol
        change, merger or delisting affects a held security and no matching
        ledger transaction was recorded on/after the effective date, the
        position is marked RECONCILIATION_REQUIRED.
        """
        positions = self.latest_positions(portfolio_id, as_of=as_of)
        if not positions:
            return ()
        earliest_by_stock = self._earliest_position_date(portfolio_id, as_of=as_of)
        reconciliations: list[PositionReconciliation] = []
        for position in positions:
            stock = self.session.get(Stock, position.stock_id)
            symbol = stock.symbol if stock is not None else str(position.stock_id)
            earliest = earliest_by_stock.get(position.stock_id)
            actions = tuple(
                self.session.scalars(
                    select(CorporateAction)
                    .where(
                        CorporateAction.stock_id == position.stock_id,
                        CorporateAction.effective_date
                        >= (earliest if earliest is not None else as_of.date()),
                        CorporateAction.effective_date <= as_of.date(),
                    )
                    .order_by(CorporateAction.effective_date)
                )
            )
            pending: list[dict[str, object]] = []
            for action in actions:
                if not self._action_reconciled(portfolio_id, position.stock_id, action):
                    pending.append(
                        {
                            "action_id": action.action_id,
                            "action_type": action.action_type,
                            "effective_date": action.effective_date.isoformat(),
                            "source": action.source,
                        }
                    )
            reconciliations.append(
                PositionReconciliation(
                    symbol=symbol,
                    stock_id=position.stock_id,
                    status=("RECONCILIATION_REQUIRED" if pending else "OK"),
                    actions=tuple(pending),
                )
            )
        return tuple(reconciliations)

    # ------------------------------------------------------------------

    def _earliest_position_date(
        self, portfolio_id: int, *, as_of: datetime
    ) -> dict[int, date]:
        rows = tuple(
            self.session.scalars(
                select(PortfolioPosition)
                .where(
                    PortfolioPosition.portfolio_id == portfolio_id,
                    PortfolioPosition.as_of_date <= as_of.date(),
                )
                .order_by(PortfolioPosition.as_of_date, PortfolioPosition.id)
            )
        )
        output: dict[int, date] = {}
        for row in rows:
            output.setdefault(row.stock_id, row.as_of_date)
        return output

    def _action_reconciled(
        self, portfolio_id: int, stock_id: int, action: CorporateAction
    ) -> bool:
        expected_type = {
            "split": "split",
            "reverse_split": "split",
            "cash_dividend": "dividend",
            "stock_dividend": "split",
            "symbol_change": "symbol_change",
            "merger_cash": "sell",
            "merger_stock": "sell",
            "delisting": "sell",
        }.get(action.action_type)
        if expected_type is None:
            return False
        transaction = self.session.scalar(
            select(PortfolioTransaction)
            .where(
                PortfolioTransaction.portfolio_id == portfolio_id,
                PortfolioTransaction.stock_id == stock_id,
                PortfolioTransaction.transaction_type == expected_type,
                PortfolioTransaction.trade_date >= action.effective_date,
            )
            .order_by(PortfolioTransaction.trade_date, PortfolioTransaction.id)
            .limit(1)
        )
        return transaction is not None

    def _external_flow(
        self,
        portfolio_id: int,
        *,
        start: datetime | None,
        end: datetime,
    ) -> float:
        statement = select(PortfolioTransaction).where(
            PortfolioTransaction.portfolio_id == portfolio_id,
            PortfolioTransaction.trade_date <= end.date(),
            PortfolioTransaction.transaction_type.in_(("deposit", "withdrawal")),
        )
        if start is not None:
            statement = statement.where(PortfolioTransaction.trade_date > start.date())
        total = Decimal("0")
        for item in self.session.scalars(statement):
            amount = item.cash_amount or Decimal("0")
            signed = amount if item.transaction_type == "deposit" else -amount
            total += signed * item.fx_rate_to_base
        return float(total)

    def _fees(
        self,
        portfolio_id: int,
        *,
        start: datetime | None,
        end: datetime,
    ) -> float:
        statement = select(PortfolioTransaction).where(
            PortfolioTransaction.portfolio_id == portfolio_id,
            PortfolioTransaction.trade_date <= end.date(),
        )
        if start is not None:
            statement = statement.where(PortfolioTransaction.trade_date > start.date())
        return float(
            sum((item.fee_amount for item in self.session.scalars(statement)), Decimal("0"))
        )


def _aware(value: datetime) -> datetime:
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value).astimezone(UTC)
