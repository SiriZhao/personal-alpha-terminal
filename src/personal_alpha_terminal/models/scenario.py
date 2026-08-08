from datetime import date
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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


class ScenarioRiskFactor(TimestampMixin, Base):
    __tablename__ = "scenario_risk_factors"
    __table_args__ = (
        CheckConstraint(
            "shock_unit IN ('decimal_return', 'basis_points', 'standard_score')",
            name="valid_scenario_factor_unit",
        ),
        CheckConstraint(
            "normalized_minimum < normalized_maximum",
            name="valid_scenario_factor_bounds",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    shock_unit: Mapped[str] = mapped_column(String(24), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_minimum: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )
    normalized_maximum: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )

    exposures: Mapped[list["AssetRiskFactorExposure"]] = relationship(
        back_populates="factor",
    )


class AssetRiskFactorExposure(TimestampMixin, Base):
    __tablename__ = "asset_risk_factor_exposures"
    __table_args__ = (
        CheckConstraint(
            "sensitivity_low <= sensitivity AND sensitivity <= sensitivity_high",
            name="valid_asset_factor_sensitivity_interval",
        ),
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 100",
            name="valid_asset_factor_confidence",
        ),
        UniqueConstraint(
            "stock_id",
            "factor_id",
            "as_of_date",
            "source",
            name="uq_asset_factor_exposure_version",
        ),
        Index(
            "ix_asset_factor_exposure_lookup",
            "stock_id",
            "factor_id",
            "as_of_date",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="CASCADE"),
        nullable=False,
    )
    factor_id: Mapped[int] = mapped_column(
        ForeignKey("scenario_risk_factors.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    sensitivity: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    sensitivity_low: Mapped[Decimal] = mapped_column(
        Numeric(18, 10),
        nullable=False,
    )
    sensitivity_high: Mapped[Decimal] = mapped_column(
        Numeric(18, 10),
        nullable=False,
    )
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(256), nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False)

    factor: Mapped[ScenarioRiskFactor] = relationship(back_populates="exposures")


class ScenarioDefinitionModel(TimestampMixin, Base):
    __tablename__ = "scenario_definitions"
    __table_args__ = (
        CheckConstraint(
            "scenario_type IN ('custom', 'historical', 'hypothetical')",
            name="valid_scenario_definition_type",
        ),
        CheckConstraint(
            "evidence_level IN "
            "('source_backed', 'calibrated_historical', "
            "'user_assumption', 'illustrative')",
            name="valid_scenario_evidence_level",
        ),
        UniqueConstraint("name", "version", name="uq_scenario_definition_version"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    scenario_type: Mapped[str] = mapped_column(String(24), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    definition_fingerprint: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )
    factor_shocks: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
    )
    currency_shocks: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    evidence_level: Mapped[str] = mapped_column(String(32), nullable=False)
    data_sources: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    historical_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    historical_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    runs: Mapped[list["ScenarioSimulationRun"]] = relationship(
        back_populates="definition",
    )


class ScenarioSimulationRun(TimestampMixin, Base):
    __tablename__ = "scenario_simulation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('completed', 'failed')",
            name="valid_scenario_run_status",
        ),
        CheckConstraint(
            "risk_level IN ('Low', 'Medium', 'High', 'Critical')",
            name="valid_scenario_risk_level",
        ),
        CheckConstraint(
            "mapped_weight >= 0 AND mapped_weight <= 1 "
            "AND uncovered_weight >= 0 AND uncovered_weight <= 1",
            name="valid_scenario_coverage",
        ),
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 90",
            name="valid_scenario_run_confidence",
        ),
        CheckConstraint(
            "original_value > 0 AND stressed_value >= 0",
            name="valid_scenario_values",
        ),
        Index(
            "ix_scenario_runs_portfolio_asof",
            "portfolio_id",
            "as_of_date",
            "created_at",
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
    definition_id: Mapped[int] = mapped_column(
        ForeignKey("scenario_definitions.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    original_value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    stressed_value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    pnl_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    pnl_percent: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    pnl_percent_low: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    pnl_percent_high: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    mapped_weight: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    uncovered_weight: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False)
    data_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    definition: Mapped[ScenarioDefinitionModel] = relationship(back_populates="runs")
    impacts: Mapped[list["ScenarioAssetImpact"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class ScenarioAssetImpact(Base):
    __tablename__ = "scenario_asset_impacts"
    __table_args__ = (
        CheckConstraint("weight >= 0 AND weight <= 1", name="valid_scenario_asset_weight"),
        CheckConstraint(
            "original_value >= 0 AND stressed_value >= 0",
            name="valid_scenario_asset_values",
        ),
        UniqueConstraint(
            "run_id",
            "stock_id",
            name="uq_scenario_asset_impact_run_stock",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("scenario_simulation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    original_value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    factor_return: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    currency_return: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    combined_return: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    return_low: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    return_high: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    contribution: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    stressed_value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    mapped: Mapped[bool] = mapped_column(Boolean, nullable=False)
    factor_contributions: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
    )

    run: Mapped[ScenarioSimulationRun] = relationship(back_populates="impacts")
