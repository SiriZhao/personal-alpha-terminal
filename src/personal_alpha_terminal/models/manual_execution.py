from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from personal_alpha_terminal.models.base import Base, TimestampMixin


class ManualExecutionOrder(TimestampMixin, Base):
    __tablename__ = "manual_execution_orders_v2"
    __table_args__ = (
        CheckConstraint("side IN ('BUY', 'SELL')", name="valid_manual_order_side_v2"),
        CheckConstraint(
            "status IN ('PENDING', 'PARTIAL', 'FILLED', 'CANCELLED', 'MODIFIED')",
            name="valid_manual_order_status_v2",
        ),
        CheckConstraint("approved_quantity > 0", name="positive_manual_order_quantity_v2"),
        CheckConstraint("expected_price > 0", name="positive_manual_order_price_v2"),
        CheckConstraint("expected_cost >= 0", name="nonnegative_manual_order_cost_v2"),
        UniqueConstraint("recommendation_record_id", name="uq_manual_order_recommendation_v2"),
        UniqueConstraint("order_id", name="uq_manual_order_id_v2"),
        Index("ix_manual_order_run_status_v2", "run_id", "status"),
        Index("ix_manual_order_portfolio_v2", "portfolio_id"),
        Index("ix_manual_order_stock_v2", "stock_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    order_id: Mapped[str] = mapped_column(String(96), nullable=False)
    recommendation_record_id: Mapped[int] = mapped_column(
        ForeignKey("quant_decision_recommendations.id", ondelete="RESTRICT"), nullable=False
    )
    recommendation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("quant_decision_runs.id", ondelete="RESTRICT"), nullable=False
    )
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="RESTRICT"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    approved_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    original_approved_quantity: Mapped[Decimal] = mapped_column(
        Numeric(24, 8), nullable=False
    )
    expected_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    expected_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    status_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ManualExecutionFill(Base):
    __tablename__ = "manual_execution_fills_v2"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="positive_manual_fill_quantity_v2"),
        CheckConstraint("price > 0", name="positive_manual_fill_price_v2"),
        CheckConstraint("fee >= 0", name="nonnegative_manual_fill_fee_v2"),
        UniqueConstraint("fill_id", name="uq_manual_fill_id_v2"),
        Index("ix_manual_fill_order_time_v2", "order_id", "executed_at"),
        Index("ix_manual_fill_ledger_transaction_v2", "ledger_transaction_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    fill_id: Mapped[str] = mapped_column(String(128), nullable=False)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("manual_execution_orders_v2.id", ondelete="RESTRICT"), nullable=False
    )
    recommendation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ledger_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_transactions.id", ondelete="RESTRICT"), nullable=False
    )
