from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from personal_alpha_terminal.models.base import Base, TimestampMixin
from personal_alpha_terminal.models.market import Stock


class Event(TimestampMixin, Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_type_time", "event_type", "occurred_at"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    stock_id: Mapped[int | None] = mapped_column(
        ForeignKey("security_master.id"), index=True, nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    stock: Mapped[Stock | None] = relationship(back_populates="events")


class Signal(TimestampMixin, Base):
    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint(
            "direction IN ('long', 'short', 'neutral')",
            name="valid_direction",
        ),
        Index("ix_signals_stock_time", "stock_id", "generated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("security_master.id"), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)

    stock: Mapped[Stock] = relationship(back_populates="signals")
