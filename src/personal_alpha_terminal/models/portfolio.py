from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from personal_alpha_terminal.models.base import Base, TimestampMixin
from personal_alpha_terminal.models.market import Stock


class Portfolio(TimestampMixin, Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    base_currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    cash_balance: Mapped[Decimal] = mapped_column(
        Numeric(24, 4),
        default=Decimal("0"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(64),
        default="manual",
        nullable=False,
        server_default="manual",
    )
    schema_version: Mapped[str] = mapped_column(
        String(32),
        default="portfolio-v1",
        nullable=False,
        server_default="portfolio-v1",
    )

    positions: Mapped[list["PortfolioPosition"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
    )
    transactions: Mapped[list["PortfolioTransaction"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
    )
    allocation_targets: Mapped[list["PortfolioAllocationTarget"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
    )


class PortfolioPosition(TimestampMixin, Base):
    __tablename__ = "portfolio_positions"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "stock_id",
            "as_of_date",
            name="uq_positions_portfolio_stock_date",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"), index=True, nullable=False
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    average_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)

    portfolio: Mapped[Portfolio] = relationship(back_populates="positions")
    stock: Mapped[Stock] = relationship(back_populates="positions")


class PortfolioTransaction(Base):
    """Immutable portfolio ledger event used to reconstruct actual performance."""

    __tablename__ = "portfolio_transactions"
    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('buy', 'sell', 'dividend', 'fee', "
            "'deposit', 'withdrawal', 'split')",
            name="valid_portfolio_transaction_type",
        ),
        CheckConstraint("quantity IS NULL OR quantity > 0", name="positive_transaction_quantity"),
        CheckConstraint("unit_price IS NULL OR unit_price > 0", name="positive_transaction_price"),
        CheckConstraint("cash_amount IS NULL OR cash_amount > 0", name="positive_cash_amount"),
        CheckConstraint("fee_amount >= 0", name="nonnegative_transaction_fee"),
        CheckConstraint("fx_rate_to_base > 0", name="positive_transaction_fx_rate"),
        CheckConstraint("settlement_date >= trade_date", name="valid_transaction_settlement"),
        CheckConstraint(
            "available_time >= event_time",
            name="valid_transaction_availability",
        ),
        CheckConstraint(
            "(transaction_type IN ('buy', 'sell') AND stock_id IS NOT NULL "
            "AND quantity IS NOT NULL AND unit_price IS NOT NULL AND cash_amount IS NULL) OR "
            "(transaction_type = 'dividend' AND stock_id IS NOT NULL "
            "AND cash_amount IS NOT NULL AND quantity IS NULL AND unit_price IS NULL) OR "
            "(transaction_type = 'split' AND stock_id IS NOT NULL "
            "AND quantity IS NOT NULL AND unit_price IS NULL AND cash_amount IS NULL) OR "
            "(transaction_type IN ('deposit', 'withdrawal') AND stock_id IS NULL "
            "AND cash_amount IS NOT NULL AND quantity IS NULL AND unit_price IS NULL) OR "
            "(transaction_type = 'fee' AND cash_amount IS NOT NULL "
            "AND quantity IS NULL AND unit_price IS NULL)",
            name="valid_transaction_payload",
        ),
        UniqueConstraint(
            "portfolio_id",
            "source",
            "external_id",
            name="uq_portfolio_transaction_external_id",
        ),
        Index(
            "ix_portfolio_transactions_portfolio_trade_date",
            "portfolio_id",
            "trade_date",
            "id",
        ),
        Index(
            "ix_portfolio_transactions_portfolio_available",
            "portfolio_id",
            "available_time",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id: Mapped[int | None] = mapped_column(
        ForeignKey("security_master.id", ondelete="RESTRICT"),
        index=True,
        nullable=True,
    )
    transaction_type: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    settlement_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    fee_amount: Mapped[Decimal] = mapped_column(
        Numeric(24, 6),
        default=Decimal("0"),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fx_rate_to_base: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="manual", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    portfolio: Mapped[Portfolio] = relationship(back_populates="transactions")
    stock: Mapped[Stock | None] = relationship()


class PortfolioAllocationTarget(TimestampMixin, Base):
    """Versioned analytical target; it never represents an executable order."""

    __tablename__ = "portfolio_allocation_targets"
    __table_args__ = (
        CheckConstraint(
            "target_weight >= 0 AND target_weight <= 1",
            name="valid_allocation_target_weight",
        ),
        CheckConstraint(
            "(stock_id IS NOT NULL AND cash_currency IS NULL) OR "
            "(stock_id IS NULL AND cash_currency IS NOT NULL)",
            name="valid_allocation_target_asset",
        ),
        UniqueConstraint(
            "portfolio_id",
            "effective_date",
            "stock_id",
            name="uq_portfolio_target_stock_date",
        ),
        UniqueConstraint(
            "portfolio_id",
            "effective_date",
            "cash_currency",
            name="uq_portfolio_target_cash_date",
        ),
        Index(
            "ix_portfolio_targets_portfolio_effective",
            "portfolio_id",
            "effective_date",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id: Mapped[int | None] = mapped_column(
        ForeignKey("security_master.id", ondelete="RESTRICT"),
        index=True,
        nullable=True,
    )
    cash_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_weight: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    portfolio: Mapped[Portfolio] = relationship(back_populates="allocation_targets")
    stock: Mapped[Stock | None] = relationship()
