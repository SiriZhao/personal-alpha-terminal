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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from personal_alpha_terminal.models.base import Base, TimestampMixin
from personal_alpha_terminal.models.market import Stock


class QuantDecisionRun(TimestampMixin, Base):
    __tablename__ = "quant_decision_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('generated', 'no_decision', 'blocked')",
            name="valid_quant_decision_run_status",
        ),
        CheckConstraint(
            "gate_status IN ('APPROVED', 'RESEARCH_ONLY', 'DEGRADED', 'BLOCKED')",
            name="valid_quant_decision_gate_status",
        ),
        UniqueConstraint(
            "portfolio_id",
            "as_of_time",
            "input_fingerprint",
            name="uq_quant_decision_run_input",
        ),
        Index("ix_quant_decision_run_latest", "portfolio_id", "as_of_time"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )
    as_of_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    gate_status: Mapped[str] = mapped_column(String(16), nullable=False)
    authorization_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    blockers: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    recommendations: Mapped[list["QuantDecisionRecommendation"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class QuantDecisionRecommendation(TimestampMixin, Base):
    __tablename__ = "quant_decision_recommendations"
    __table_args__ = (
        CheckConstraint(
            "action IN ('BUY', 'ADD', 'REDUCE', 'SELL', 'HOLD', 'WATCH')",
            name="valid_quant_decision_action",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected', 'watch')",
            name="valid_quant_decision_review_status",
        ),
        CheckConstraint(
            "current_weight >= 0 AND current_weight <= 1 AND "
            "target_weight >= 0 AND target_weight <= 1",
            name="valid_quant_decision_weights",
        ),
        CheckConstraint(
            "quant_score >= 0 AND quant_score <= 100 AND "
            "confidence_score >= 0 AND confidence_score <= 100",
            name="valid_quant_decision_scores",
        ),
        CheckConstraint("reference_price > 0", name="positive_decision_reference_price"),
        UniqueConstraint("run_id", "stock_id", name="uq_quant_decision_run_stock"),
        Index("ix_quant_decision_pending", "review_status", "expires_at"),
        Index("ix_quant_decision_recommendation_stock", "stock_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    recommendation_id: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("quant_decision_runs.id", ondelete="CASCADE"), nullable=False
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    current_weight: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    target_weight: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    quant_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    component_scores: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    rationale: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    risk_factors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_grade: Mapped[str] = mapped_column(String(32), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    suggested_shares: Mapped[int] = mapped_column(BigInteger, nullable=False)
    earliest_execution_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

    run: Mapped[QuantDecisionRun] = relationship(back_populates="recommendations")
    stock: Mapped[Stock] = relationship()
    history: Mapped[list["DecisionHistory"]] = relationship(
        back_populates="recommendation",
        cascade="all, delete-orphan",
    )


class DecisionHistory(Base):
    __tablename__ = "decision_history"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('accepted', 'rejected', 'watch')",
            name="valid_decision_history_choice",
        ),
        UniqueConstraint("recommendation_id", name="uq_decision_history_recommendation"),
        Index("ix_decision_history_decided", "decided_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    recommendation_id: Mapped[int] = mapped_column(
        ForeignKey("quant_decision_recommendations.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    recommendation: Mapped[QuantDecisionRecommendation] = relationship(
        back_populates="history"
    )
