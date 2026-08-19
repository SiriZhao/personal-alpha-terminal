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


class IssuerSecurityIdentity(TimestampMixin, Base):
    """Canonical PIT CIK-to-issuer-to-security mapping.

    This is an identity extension of ``security_master``, not a second master.
    A row may intentionally have a resolved issuer with a null security mapping
    until exact PIT evidence exists.
    """

    __tablename__ = "issuer_security_identity_history"
    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_from <= effective_to",
            name="valid_issuer_security_period",
        ),
        CheckConstraint(
            "permanent_security_id IS NULL OR ticker_as_of IS NOT NULL",
            name="issuer_security_mapping_requires_ticker",
        ),
        UniqueConstraint(
            "cik",
            "evidence_identifier",
            "ticker_as_of",
            "effective_from",
            "source",
            "source_version",
            name="uq_issuer_security_identity_vintage",
        ),
        Index(
            "ix_issuer_security_identity_pit",
            "cik",
            "effective_from",
            "effective_to",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    cik: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False, index=True
    )
    issuer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    issuer_name: Mapped[str] = mapped_column(String(256), nullable=False)
    stock_id: Mapped[int | None] = mapped_column(
        ForeignKey("security_master.id", ondelete="SET NULL"), nullable=True, index=True
    )
    permanent_security_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ticker_as_of: Mapped[str | None] = mapped_column(String(32), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mapping_source_type: Mapped[str] = mapped_column(String(48), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_version: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_identifier: Mapped[str | None] = mapped_column(String(512), nullable=True)
    evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SecurityLifecycleEvent(Base):
    """Append-only cross-source lifecycle evidence for an internal security ID.

    Existing listing, delisting, alias, and corporate-action tables remain the
    operational records.  This unified ledger preserves source-native event
    provenance, including unresolved predecessor/successor links, for an
    eventual certified historical import.
    """

    __tablename__ = "security_lifecycle_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('LISTING', 'DELISTING', 'SUSPENSION', 'TICKER_CHANGE', "
            "'NAME_CHANGE', 'MERGER', 'ACQUISITION', 'SPINOFF', 'SPLIT', "
            "'REVERSE_SPLIT', 'EXCHANGE_CHANGE', 'OTHER')",
            name="valid_security_lifecycle_event_type",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="valid_security_lifecycle_confidence",
        ),
        CheckConstraint(
            "announcement_timestamp IS NULL OR announcement_timestamp <= known_at",
            name="valid_security_lifecycle_announcement",
        ),
        UniqueConstraint(
            "event_id",
            "source",
            "source_record_id",
            name="uq_security_lifecycle_source_record",
        ),
        Index(
            "ix_security_lifecycle_security_pit",
            "security_id",
            "effective_date",
            "known_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    stock_id: Mapped[int | None] = mapped_column(
        ForeignKey("security_master.id", ondelete="SET NULL"), nullable=True, index=True
    )
    issuer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    security_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    old_ticker: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_ticker: Mapped[str | None] = mapped_column(String(32), nullable=True)
    old_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    new_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    announcement_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    predecessor_security_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    successor_security_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(512), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)


class SecFilingEvidence(Base):
    """Immutable SEC filing metadata, keyed by CIK and accession number."""

    __tablename__ = "sec_filing_evidence"
    __table_args__ = (
        CheckConstraint("cik > 0", name="positive_sec_filing_cik"),
        CheckConstraint(
            "acceptance_datetime <= known_at AND known_at <= fetched_at",
            name="valid_sec_filing_timestamps",
        ),
        UniqueConstraint("cik", "accession_number", name="uq_sec_filing_accession"),
        Index("ix_sec_filing_known_at", "cik", "known_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    cik: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False, index=True
    )
    issuer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    issuer_name: Mapped[str] = mapped_column(String(256), nullable=False)
    accession_number: Mapped[str] = mapped_column(String(32), nullable=False)
    form: Mapped[str] = mapped_column(String(32), nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    acceptance_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    primary_document: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="sec_edgar")
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_identity: Mapped[str] = mapped_column(String(256), nullable=False)


class SecCompanyFactEvidence(Base):
    """One accepted SEC XBRL fact, retaining every filing revision immutably."""

    __tablename__ = "sec_company_fact_evidence"
    __table_args__ = (
        CheckConstraint("cik > 0", name="positive_sec_fact_cik"),
        CheckConstraint(
            "acceptance_datetime <= known_at AND known_at <= fetched_at",
            name="valid_sec_fact_timestamps",
        ),
        UniqueConstraint("revision_identity", name="uq_sec_fact_revision_identity"),
        Index(
            "ix_sec_fact_pit",
            "cik",
            "taxonomy",
            "concept",
            "known_at",
            "period_end",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    filing_id: Mapped[int] = mapped_column(
        ForeignKey("sec_filing_evidence.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    stock_id: Mapped[int | None] = mapped_column(
        ForeignKey("security_master.id", ondelete="SET NULL"), nullable=True, index=True
    )
    issuer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cik: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False, index=True
    )
    taxonomy: Mapped[str] = mapped_column(String(64), nullable=False)
    concept: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(36, 10), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_period: Mapped[str | None] = mapped_column(String(16), nullable=True)
    form: Mapped[str] = mapped_column(String(32), nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    acceptance_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accession_number: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision_identity: Mapped[str] = mapped_column(String(512), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


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


class ManualExecutionRecord(TimestampMixin, Base):
    """Immutable audit record for a broker execution reported by the user.

    This table does not update holdings.  A separately validated portfolio
    transaction is required before a Schwab/manual execution changes the real
    portfolio ledger.
    """

    __tablename__ = "manual_execution_records"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'PARTIAL', 'FILLED', 'CANCELLED', 'MODIFIED')",
            name="valid_manual_execution_status",
        ),
        UniqueConstraint("execution_id", name="uq_manual_execution_id"),
        Index("ix_manual_execution_ticket_time", "ticket_id", "reported_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(96), nullable=False)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("manual_rebalance_tickets.id", ondelete="CASCADE"), nullable=False
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_shares: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actual_shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    expected_price: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    actual_price: Mapped[float | None] = mapped_column(Numeric(20, 6))
    expected_cost: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    actual_fee: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    slippage: Mapped[float | None] = mapped_column(Numeric(20, 6))
    execution_deviation: Mapped[float | None] = mapped_column(Numeric(20, 6))
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
