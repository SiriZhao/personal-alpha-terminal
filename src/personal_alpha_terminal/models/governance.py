from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from personal_alpha_terminal.models.base import Base, TimestampMixin

_ID = BigInteger().with_variant(Integer, "sqlite")


class ExperimentRecord(TimestampMixin, Base):
    __tablename__ = "quant_experiments"
    __table_args__ = (
        UniqueConstraint("experiment_id", "version", name="uq_quant_experiment_version"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(96), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    research_question: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    data_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    universe_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    factor_versions: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    parameter_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    train_start: Mapped[date] = mapped_column(Date, nullable=False)
    train_end: Mapped[date] = mapped_column(Date, nullable=False)
    validation_start: Mapped[date] = mapped_column(Date, nullable=False)
    validation_end: Mapped[date] = mapped_column(Date, nullable=False)
    embargo_sessions: Mapped[int] = mapped_column(Integer, nullable=False)
    locked_test_start: Mapped[date] = mapped_column(Date, nullable=False)
    locked_test_end: Mapped[date] = mapped_column(Date, nullable=False)
    benchmark_versions: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    cost_model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    code_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExperimentResultRecord(Base):
    __tablename__ = "quant_experiment_results"
    __table_args__ = (
        UniqueConstraint("experiment_record_id", "stage", name="uq_experiment_result_stage"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    experiment_record_id: Mapped[int] = mapped_column(
        ForeignKey("quant_experiments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metrics: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    data_mining_risk: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PortfolioReconciliationRecord(Base):
    __tablename__ = "portfolio_reconciliations"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "snapshot_hash", name="uq_portfolio_reconciliation_hash"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    broker: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    differences: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    reconciled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_file_hash: Mapped[str | None] = mapped_column(String(64))
