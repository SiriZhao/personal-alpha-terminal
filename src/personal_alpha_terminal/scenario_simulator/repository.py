from dataclasses import asdict
from datetime import date
from decimal import Decimal
from hashlib import sha256
from json import dumps

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.analysis.market_graph.repository import (
    MarketGraphRepository,
)
from personal_alpha_terminal.models import (
    AssetRiskFactorExposure,
    Portfolio,
    PortfolioRiskMetric,
    PortfolioRiskRun,
    ScenarioAssetImpact,
    ScenarioDefinitionModel,
    ScenarioRiskFactor,
    ScenarioSimulationRun,
    Stock,
)
from personal_alpha_terminal.scenario_simulator.schemas import (
    AssetFactorExposure,
    RiskFactorDefinition,
    ScenarioDefinition,
    ScenarioPortfolio,
    ScenarioPosition,
    ScenarioResult,
)


class ScenarioRepository:
    """Persist versioned mappings, definitions, and immutable scenario evidence."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def ensure_factors(
        self,
        factors: tuple[RiskFactorDefinition, ...],
    ) -> dict[str, ScenarioRiskFactor]:
        existing = {
            item.code: item
            for item in self.session.scalars(
                select(ScenarioRiskFactor).where(
                    ScenarioRiskFactor.code.in_(tuple(item.code for item in factors))
                )
            )
        }
        for definition in factors:
            model = existing.get(definition.code)
            if model is None:
                model = ScenarioRiskFactor(
                    code=definition.code,
                    name=definition.name,
                    category=definition.category,
                    shock_unit=definition.shock_unit,
                    description=definition.description,
                    normalized_minimum=_decimal(definition.normalized_minimum),
                    normalized_maximum=_decimal(definition.normalized_maximum),
                )
                self.session.add(model)
                existing[definition.code] = model
                continue
            current = (
                model.name,
                model.category,
                model.shock_unit,
                model.description,
                float(model.normalized_minimum),
                float(model.normalized_maximum),
            )
            expected = (
                definition.name,
                definition.category,
                definition.shock_unit,
                definition.description,
                definition.normalized_minimum,
                definition.normalized_maximum,
            )
            if current != expected:
                raise ValueError(f"persisted risk factor definition changed: {definition.code}")
        self.session.flush()
        return existing

    def save_exposures(
        self,
        exposures: tuple[AssetFactorExposure, ...],
        factors: tuple[RiskFactorDefinition, ...],
    ) -> None:
        if not exposures:
            return
        factor_models = self.ensure_factors(factors)
        stock_ids = {item.asset_id for item in exposures}
        existing_stock_ids = set(
            self.session.scalars(select(Stock.id).where(Stock.id.in_(stock_ids)))
        )
        if existing_stock_ids != stock_ids:
            raise ValueError("asset exposure references an unknown stock")
        for item in exposures:
            factor = factor_models.get(item.factor_code)
            if factor is None:
                raise ValueError(f"unknown exposure factor: {item.factor_code}")
            duplicate = self.session.scalar(
                select(AssetRiskFactorExposure).where(
                    AssetRiskFactorExposure.stock_id == item.asset_id,
                    AssetRiskFactorExposure.factor_id == factor.id,
                    AssetRiskFactorExposure.as_of_date == item.as_of_date,
                    AssetRiskFactorExposure.source == item.source,
                )
            )
            if duplicate is not None:
                existing_values = (
                    float(duplicate.sensitivity),
                    float(duplicate.sensitivity_low),
                    float(duplicate.sensitivity_high),
                    duplicate.method,
                    duplicate.confidence_score,
                )
                requested_values = (
                    item.sensitivity,
                    item.sensitivity_low,
                    item.sensitivity_high,
                    item.method,
                    item.confidence_score,
                )
                if existing_values == requested_values:
                    continue
                raise ValueError(
                    "asset exposure version already exists with different values; "
                    "use a new as-of date or source label"
                )
            self.session.add(
                AssetRiskFactorExposure(
                    stock_id=item.asset_id,
                    factor_id=factor.id,
                    as_of_date=item.as_of_date,
                    sensitivity=_decimal(item.sensitivity),
                    sensitivity_low=_decimal(item.sensitivity_low),
                    sensitivity_high=_decimal(item.sensitivity_high),
                    method=item.method,
                    source=item.source,
                    confidence_score=item.confidence_score,
                )
            )
        self.session.flush()

    def load_exposures(
        self,
        *,
        stock_ids: tuple[int, ...],
        as_of_date: date,
    ) -> tuple[AssetFactorExposure, ...]:
        if not stock_ids:
            return ()
        models = self.session.scalars(
            select(AssetRiskFactorExposure)
            .join(AssetRiskFactorExposure.factor)
            .where(
                AssetRiskFactorExposure.stock_id.in_(stock_ids),
                AssetRiskFactorExposure.as_of_date <= as_of_date,
            )
            .order_by(
                AssetRiskFactorExposure.stock_id,
                ScenarioRiskFactor.code,
                AssetRiskFactorExposure.as_of_date.desc(),
                AssetRiskFactorExposure.confidence_score.desc(),
                AssetRiskFactorExposure.id.desc(),
            )
        )
        latest: dict[tuple[int, str], AssetFactorExposure] = {}
        for model in models:
            key = (model.stock_id, model.factor.code)
            latest.setdefault(
                key,
                AssetFactorExposure(
                    asset_id=model.stock_id,
                    factor_code=model.factor.code,
                    sensitivity=float(model.sensitivity),
                    sensitivity_low=float(model.sensitivity_low),
                    sensitivity_high=float(model.sensitivity_high),
                    as_of_date=model.as_of_date,
                    method=model.method,
                    source=model.source,
                    confidence_score=model.confidence_score,
                ),
            )
        return tuple(latest[key] for key in sorted(latest))

    def load_latest_portfolio(self, portfolio_id: int) -> ScenarioPortfolio:
        portfolio = self.session.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise ValueError("portfolio does not exist")
        run = self.session.scalar(
            select(PortfolioRiskRun)
            .where(
                PortfolioRiskRun.portfolio_id == portfolio_id,
                PortfolioRiskRun.status == "completed",
            )
            .order_by(
                PortfolioRiskRun.as_of_date.desc(),
                PortfolioRiskRun.created_at.desc(),
                PortfolioRiskRun.id.desc(),
            )
            .limit(1)
        )
        if run is None:
            raise ValueError("portfolio requires a completed risk valuation before scenarios")
        metric = self.session.scalar(
            select(PortfolioRiskMetric).where(PortfolioRiskMetric.run_id == run.id)
        )
        if metric is None:
            raise ValueError("completed risk run is missing its metric snapshot")
        rows = metric.position_risks
        stock_ids = {_as_int(item["stock_id"]) for item in rows if "stock_id" in item}
        stocks = {
            item.id: item
            for item in self.session.scalars(select(Stock).where(Stock.id.in_(stock_ids)))
        }
        if set(stocks) != stock_ids:
            raise ValueError("risk snapshot references missing securities")
        total_value = float(metric.total_value)
        positions: list[ScenarioPosition] = []
        for row in rows:
            stock_id = _as_int(row["stock_id"])
            market_value = _as_float(row["market_value"])
            weight = market_value / total_value
            positions.append(
                ScenarioPosition(
                    instrument=MarketGraphRepository.instrument(stocks[stock_id]),
                    currency=str(row["currency"]).upper(),
                    market_value=market_value,
                    weight=weight,
                )
            )
        cash_value = total_value - sum(item.market_value for item in positions)
        tolerance = max(0.01, total_value * 1e-8)
        if cash_value < -tolerance:
            raise ValueError("risk snapshot positions exceed portfolio total value")
        return ScenarioPortfolio(
            portfolio_id=portfolio.id,
            portfolio_name=portfolio.name,
            base_currency=portfolio.base_currency.upper(),
            as_of_date=run.as_of_date,
            total_value=total_value,
            cash_value=max(0.0, cash_value),
            positions=tuple(sorted(positions, key=lambda item: item.instrument.id)),
        )

    def save_definition(
        self,
        scenario: ScenarioDefinition,
    ) -> ScenarioDefinitionModel:
        fingerprint = _scenario_fingerprint(scenario)
        existing = self.session.scalar(
            select(ScenarioDefinitionModel).where(
                ScenarioDefinitionModel.definition_fingerprint == fingerprint
            )
        )
        if existing is not None:
            return existing
        latest_version = self.session.scalar(
            select(func.max(ScenarioDefinitionModel.version)).where(
                ScenarioDefinitionModel.name == scenario.name
            )
        )
        model = ScenarioDefinitionModel(
            name=scenario.name,
            version=(latest_version or 0) + 1,
            scenario_type=scenario.scenario_type,
            description=scenario.description,
            definition_fingerprint=fingerprint,
            factor_shocks=[
                {
                    "factor_code": item.factor_code,
                    "magnitude": item.magnitude,
                    "unit": item.unit,
                    "rationale": item.rationale,
                }
                for item in scenario.factor_shocks
            ],
            currency_shocks={
                currency.upper(): shock for currency, shock in scenario.currency_shocks.items()
            },
            evidence_level=scenario.evidence_level,
            data_sources=list(scenario.data_sources),
            historical_start=scenario.historical_start,
            historical_end=scenario.historical_end,
            is_builtin=scenario.is_builtin,
        )
        self.session.add(model)
        self.session.flush()
        return model

    def save_result(
        self,
        result: ScenarioResult,
        definition: ScenarioDefinitionModel,
    ) -> ScenarioSimulationRun:
        run = ScenarioSimulationRun(
            portfolio_id=result.portfolio_id,
            definition_id=definition.id,
            as_of_date=result.as_of_date,
            status="completed",
            base_currency=result.base_currency,
            original_value=_decimal(result.original_value),
            stressed_value=_decimal(result.stressed_value),
            pnl_amount=_decimal(result.pnl_amount),
            pnl_percent=_decimal(result.pnl_percent),
            pnl_percent_low=_decimal(result.pnl_percent_low),
            pnl_percent_high=_decimal(result.pnl_percent_high),
            risk_level=result.risk_level,
            mapped_weight=_decimal(result.mapped_weight),
            uncovered_weight=_decimal(result.uncovered_weight),
            confidence_score=result.confidence_score,
            data_fingerprint=result.data_fingerprint,
            warnings=list(result.warnings),
            parameters={
                "method": "linear_factor_sensitivity_plus_multiplicative_fx",
                "scenario_definition_version": definition.version,
                "scenario_definition_fingerprint": (definition.definition_fingerprint),
                "risk_thresholds": {
                    "Medium": -0.05,
                    "High": -0.10,
                    "Critical": -0.20,
                },
            },
        )
        self.session.add(run)
        self.session.flush()
        self.session.add_all(
            [
                ScenarioAssetImpact(
                    run_id=run.id,
                    stock_id=item.instrument.id,
                    currency=item.currency,
                    weight=_decimal(item.weight),
                    original_value=_decimal(item.original_value),
                    factor_return=_decimal(item.factor_return),
                    currency_return=_decimal(item.currency_return),
                    combined_return=_decimal(item.combined_return),
                    return_low=_decimal(item.return_low),
                    return_high=_decimal(item.return_high),
                    contribution=_decimal(item.contribution),
                    stressed_value=_decimal(item.stressed_value),
                    mapped=item.mapped,
                    factor_contributions=[
                        asdict(contribution) for contribution in item.factor_contributions
                    ],
                )
                for item in result.impacts
            ]
        )
        self.session.flush()
        return run


def _scenario_fingerprint(scenario: ScenarioDefinition) -> str:
    payload = {
        "name": scenario.name,
        "type": scenario.scenario_type,
        "description": scenario.description,
        "factor_shocks": [asdict(item) for item in scenario.factor_shocks],
        "currency_shocks": scenario.currency_shocks,
        "evidence_level": scenario.evidence_level,
        "data_sources": scenario.data_sources,
        "historical_start": (
            scenario.historical_start.isoformat() if scenario.historical_start is not None else None
        ),
        "historical_end": (
            scenario.historical_end.isoformat() if scenario.historical_end is not None else None
        ),
        "is_builtin": scenario.is_builtin,
    }
    return sha256(
        dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 12)))


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("persisted stock_id is not an integer")
    return int(value)


def _as_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("persisted value is not numeric")
    return float(value)
