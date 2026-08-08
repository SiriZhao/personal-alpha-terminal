from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
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

_ID = BigInteger().with_variant(Integer, "sqlite")


class SymbolAlias(Base):
    __tablename__ = "security_symbol_aliases"
    __table_args__ = (
        UniqueConstraint(
            "exchange", "symbol", "valid_from", "source", name="uq_symbol_alias_vintage"
        ),
        Index("ix_symbol_alias_pit", "exchange", "symbol", "valid_from", "valid_to"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    available_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)


class ListingHistory(Base):
    __tablename__ = "security_listing_history"
    __table_args__ = (
        UniqueConstraint("stock_id", "effective_from", name="uq_listing_history_effective"),
        Index("ix_listing_history_pit", "stock_id", "effective_from", "effective_to"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    announcement_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)


class DelistingHistory(Base):
    __tablename__ = "security_delisting_history"
    __table_args__ = (
        UniqueConstraint("stock_id", "effective_date", "revision_id", name="uq_delisting_revision"),
        Index("ix_delisting_pit", "stock_id", "available_time", "effective_date"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="CASCADE"), nullable=False, index=True
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    announcement_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    terminal_value: Mapped[float | None] = mapped_column(Float)
    terminal_currency: Mapped[str | None] = mapped_column(String(3))
    revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)


class UniverseDefinition(TimestampMixin, Base):
    __tablename__ = "universe_definitions"
    __table_args__ = (
        UniqueConstraint("definition_id", "version", name="uq_universe_definition_version"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    definition_id: Mapped[str] = mapped_column(String(96), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    rules: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_status: Mapped[str] = mapped_column(String(32), nullable=False)


class UniverseMembership(Base):
    __tablename__ = "universe_memberships"
    __table_args__ = (
        UniqueConstraint(
            "definition_id", "stock_id", "effective_from", "revision_id",
            name="uq_universe_membership_revision",
        ),
        Index("ix_universe_membership_pit", "definition_id", "effective_from", "effective_to"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    definition_id: Mapped[int] = mapped_column(
        ForeignKey("universe_definitions.id", ondelete="CASCADE"), nullable=False
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="CASCADE"), nullable=False, index=True
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    announcement_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    inclusion_reason: Mapped[str] = mapped_column(String(128), nullable=False)
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)


class TradingStatus(Base):
    __tablename__ = "security_trading_status"
    __table_args__ = (
        CheckConstraint(
            "status IN ('TRADABLE','HALTED','SUSPENDED','DELISTED','NOT_LISTED','UNKNOWN')",
            name="valid_trading_status",
        ),
        UniqueConstraint("stock_id", "effective_time", "source", name="uq_trading_status_event"),
        Index("ix_trading_status_pit", "stock_id", "available_time", "effective_time"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)


class PITTotalReturnPointRecord(Base):
    __tablename__ = "pit_total_return_points"
    __table_args__ = (
        UniqueConstraint("version_id", "trade_date", name="uq_pit_total_return_point"),
        Index("ix_pit_total_return_point_date", "version_id", "trade_date"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("pit_total_return_versions.id", ondelete="CASCADE"), nullable=False
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    raw_close: Mapped[float] = mapped_column(Float, nullable=False)
    period_return: Mapped[float] = mapped_column(Float, nullable=False)
    total_return_index: Mapped[float] = mapped_column(Float, nullable=False)
    applied_action_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class ModelApprovalRecord(TimestampMixin, Base):
    __tablename__ = "model_approval_records"
    __table_args__ = (
        UniqueConstraint("model_id", "version", name="uq_model_approval_version"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    locked_oos: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pit_certified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    survivorship_bias_controlled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    costs_included: Mapped[bool] = mapped_column(Boolean, nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(128), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
