from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from personal_alpha_terminal.models.base import Base, TimestampMixin


class MarketUniverseSnapshot(TimestampMixin, Base):
    __tablename__ = "market_universe_snapshots"
    __table_args__ = (
        CheckConstraint("market IN ('A', 'HK', 'US')", name="valid_universe_market"),
        UniqueConstraint(
            "market",
            "as_of_date",
            "source",
            "provider",
            name="uq_universe_snapshot_lineage",
        ),
        Index("ix_universe_snapshot_market_date", "market", "as_of_date"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    available_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    definition_id: Mapped[int | None] = mapped_column(
        ForeignKey("universe_definitions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    certification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="NOT_VALIDATED"
    )

    members: Mapped[list["MarketUniverseMember"]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )


class MarketUniverseMember(Base):
    __tablename__ = "market_universe_members"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "stock_id", name="uq_universe_member_stock"),
        Index("ix_universe_member_segment", "snapshot_id", "segment"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("market_universe_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    segment: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bucket: Mapped[str] = mapped_column(String(16), nullable=False)
    listing_age_bucket: Mapped[str] = mapped_column(String(16), nullable=False)
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)

    snapshot: Mapped[MarketUniverseSnapshot] = relationship(back_populates="members")


class ExchangeSession(Base):
    __tablename__ = "exchange_sessions"
    __table_args__ = (
        CheckConstraint(
            "(is_open AND open_time IS NOT NULL AND close_time IS NOT NULL) OR "
            "(NOT is_open AND open_time IS NULL AND close_time IS NULL)",
            name="valid_exchange_session_times",
        ),
        CheckConstraint(
            "open_time IS NULL OR close_time IS NULL OR open_time < close_time",
            name="valid_exchange_session_order",
        ),
        UniqueConstraint(
            "exchange",
            "session_date",
            "source",
            "provider",
            name="uq_exchange_session_lineage",
        ),
        Index("ix_exchange_sessions_date", "exchange", "session_date"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    available_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CorporateAction(Base):
    __tablename__ = "corporate_actions"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('cash_dividend', 'stock_dividend', 'split', "
            "'reverse_split', 'merger_cash', 'merger_stock', 'spin_off', 'rights', "
            "'delisting', 'symbol_change', 'adr_ratio_change')",
            name="valid_corporate_action_type",
        ),
        CheckConstraint(
            "announcement_date IS NULL OR announcement_date <= available_date",
            name="valid_corporate_action_availability",
        ),
        UniqueConstraint(
            "stock_id",
            "action_type",
            "effective_date",
            "source",
            "provider",
            name="uq_corporate_action_lineage",
        ),
        UniqueConstraint(
            "action_id",
            "revision_id",
            "provider",
            name="uq_corporate_action_revision",
        ),
        Index("ix_corporate_actions_stock_date", "stock_id", "effective_date"),
        Index("ix_corporate_actions_available", "stock_id", "available_time"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="CASCADE"),
        nullable=False,
    )
    action_id: Mapped[str] = mapped_column(String(128), nullable=False)
    revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    announcement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    available_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    split_ratio: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class MarketDataQualityRun(TimestampMixin, Base):
    __tablename__ = "market_data_quality_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'passed', 'failed', 'blocked')",
            name="valid_market_data_quality_status",
        ),
        Index("ix_market_data_quality_runs_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    history_start: Mapped[date] = mapped_column(Date, nullable=False)
    history_end: Mapped[date] = mapped_column(Date, nullable=False)
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_snapshot_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    aggregate_metrics: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    blockers: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    results: Mapped[list["MarketDataQualityResult"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class MarketDataQualityResult(Base):
    __tablename__ = "market_data_quality_results"
    __table_args__ = (
        UniqueConstraint("run_id", "stock_id", name="uq_market_quality_run_stock"),
        Index("ix_market_quality_results_status", "run_id", "status"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("market_data_quality_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    segment: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_sessions: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_sessions: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_sessions: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_rate: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    anomalous_observations: Mapped[int] = mapped_column(Integer, nullable=False)
    anomaly_rate: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    first_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    issues: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list, nullable=False)

    run: Mapped[MarketDataQualityRun] = relationship(back_populates="results")
