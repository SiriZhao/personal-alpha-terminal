from datetime import date, datetime

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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from personal_alpha_terminal.models.base import Base, TimestampMixin


class SecurityIdentifierHistory(Base):
    __tablename__ = "security_identifier_history"
    __table_args__ = (
        CheckConstraint(
            "identifier_type IN ('ticker', 'cusip', 'isin', 'figi')",
            name="valid_security_identifier_type",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from <= valid_to",
            name="valid_security_identifier_period",
        ),
        UniqueConstraint(
            "stock_id",
            "identifier_type",
            "identifier_value",
            "valid_from",
            "source",
            name="uq_security_identifier_vintage",
        ),
        Index("ix_security_identifier_lookup", "identifier_type", "identifier_value"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="CASCADE"), nullable=False
    )
    identifier_type: Mapped[str] = mapped_column(String(16), nullable=False)
    identifier_value: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FundamentalVintage(Base):
    __tablename__ = "fundamental_vintages"
    __table_args__ = (
        CheckConstraint(
            "period_type IN ('annual', 'quarterly', 'ttm')",
            name="valid_fundamental_vintage_period_type",
        ),
        CheckConstraint(
            "publication_time <= available_at AND available_at <= ingested_at",
            name="valid_fundamental_vintage_timestamps",
        ),
        UniqueConstraint(
            "stock_id",
            "filing_id",
            "revision_id",
            "source",
            name="uq_fundamental_filing_revision",
        ),
        Index("ix_fundamental_vintage_pit", "stock_id", "available_at", "fiscal_period_end"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="CASCADE"), nullable=False
    )
    fiscal_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    period_type: Mapped[str] = mapped_column(String(16), nullable=False)
    filing_id: Mapped[str] = mapped_column(String(128), nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    publication_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    is_restatement: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    original_values: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    restated_values: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_scale: Mapped[int] = mapped_column(BigInteger, nullable=False)
    accounting_standard: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PITTotalReturnVersion(TimestampMixin, Base):
    __tablename__ = "pit_total_return_versions"
    __table_args__ = (
        UniqueConstraint("version_id", name="uq_pit_total_return_version_id"),
        Index("ix_pit_total_return_stock_asof", "stock_id", "as_of_time"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="CASCADE"), nullable=False
    )
    as_of_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    data_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    adjustment_policy: Mapped[str] = mapped_column(
        String(64), nullable=False, default="point_in_time_total_return_v1"
    )
    corporate_action_ledger_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    certification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="NOT_VALIDATED"
    )


class ResearchDataCertification(TimestampMixin, Base):
    __tablename__ = "research_data_certifications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('APPROVED', 'RESEARCH_ONLY', 'DEGRADED', 'BLOCKED')",
            name="valid_research_data_certification_status",
        ),
        UniqueConstraint(
            "market",
            "asset_type",
            "data_version",
            name="uq_research_data_certification_version",
        ),
        Index("ix_research_data_certification_latest", "market", "asset_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_run_id: Mapped[int] = mapped_column(
        ForeignKey("market_data_quality_runs.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    universe_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("market_universe_snapshots.id", ondelete="RESTRICT"),
        index=True,
        nullable=True,
    )
    allow_display: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allow_backtest: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allow_portfolio_decision: Mapped[bool] = mapped_column(Boolean, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blockers: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class ModelRegistryRecord(TimestampMixin, Base):
    __tablename__ = "model_registry"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Experimental', 'Research', 'Validating', 'Tested', "
            "'Production Approved', 'Manual Pilot', 'Disabled', 'Suspended', 'Retired')",
            name="valid_model_registry_status",
        ),
        UniqueConstraint("model_id", "version", name="uq_model_registry_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    inputs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    data_requirements: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    training_period: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    validation_period: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    test_period: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    hyperparameters: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    limitations: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    approval_level: Mapped[str] = mapped_column(String(24), nullable=False)
    last_validation: Mapped[date | None] = mapped_column(Date, nullable=True)
    drift_status: Mapped[str] = mapped_column(String(24), nullable=False)


class BacktestManifestRecord(Base):
    __tablename__ = "backtest_run_manifests"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_runs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    manifest_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    code_version: Mapped[str] = mapped_column(String(64), nullable=False)
    data_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    universe_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    factor_version: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_model: Mapped[str] = mapped_column(String(128), nullable=False)
    cost_model: Mapped[str] = mapped_column(String(128), nullable=False)
    benchmark: Mapped[str] = mapped_column(String(32), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class ManualRebalanceTicketRecord(TimestampMixin, Base):
    __tablename__ = "manual_rebalance_tickets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'reviewed', 'partially_filled', 'completed', 'cancelled')",
            name="valid_manual_rebalance_status",
        ),
        Index("ix_manual_rebalance_ticket_status", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    signal_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    earliest_execution_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    authorization_id: Mapped[str] = mapped_column(String(64), nullable=False)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class ManualRebalanceFillRecord(Base):
    __tablename__ = "manual_rebalance_fills"
    __table_args__ = (Index("ix_manual_fill_ticket_time", "ticket_id", "timestamp"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("manual_rebalance_tickets.id", ondelete="CASCADE"), nullable=False
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    actual_price: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    actual_shares: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fees: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
