from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from personal_alpha_terminal.models import Portfolio, PortfolioPosition, Price, Stock


class DashboardRepository:
    """Read-only database access used by dashboard application services."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_stocks(self, *, asset_type: str | None = None) -> list[Stock]:
        statement = select(Stock).where(Stock.is_active.is_(True))
        if asset_type is not None:
            statement = statement.where(Stock.asset_type == asset_type)
        return list(self._session.scalars(statement.order_by(Stock.market, Stock.symbol)))

    def get_stock(self, stock_id: int) -> Stock | None:
        statement = select(Stock).options(selectinload(Stock.industry)).where(Stock.id == stock_id)
        return self._session.scalar(statement)

    def get_prices(
        self,
        stock_id: int,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        descending: bool = False,
        limit: int | None = None,
    ) -> list[Price]:
        statement = select(Price).where(Price.stock_id == stock_id)
        if start_date is not None:
            statement = statement.where(Price.trade_date >= start_date)
        if end_date is not None:
            statement = statement.where(Price.trade_date <= end_date)
        ordering = Price.trade_date.desc() if descending else Price.trade_date.asc()
        statement = statement.order_by(ordering, Price.ingested_at.desc(), Price.source)
        if limit is not None:
            statement = statement.limit(limit)
        return list(self._session.scalars(statement))

    def list_portfolios(self) -> list[Portfolio]:
        return list(self._session.scalars(select(Portfolio).order_by(Portfolio.name)))

    def get_portfolio(self, portfolio_id: int) -> Portfolio | None:
        return self._session.get(Portfolio, portfolio_id)

    def get_latest_positions(
        self,
        portfolio_id: int,
    ) -> tuple[date | None, list[PortfolioPosition]]:
        latest_date = self._session.scalar(
            select(func.max(PortfolioPosition.as_of_date)).where(
                PortfolioPosition.portfolio_id == portfolio_id
            )
        )
        if latest_date is None:
            return None, []
        statement = (
            select(PortfolioPosition)
            .options(selectinload(PortfolioPosition.stock).selectinload(Stock.industry))
            .where(
                PortfolioPosition.portfolio_id == portfolio_id,
                PortfolioPosition.as_of_date == latest_date,
            )
            .order_by(PortfolioPosition.stock_id)
        )
        return latest_date, list(self._session.scalars(statement))
