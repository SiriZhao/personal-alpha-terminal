from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import numpy as np
import pandas as pd

from personal_alpha_terminal.quant_engine.alpha import (
    AlphaSignal,
    AlphaValidationStatus,
    UnifiedAlphaEngine,
)
from personal_alpha_terminal.quant_engine.costs import TransactionCostModel
from personal_alpha_terminal.quant_engine.decision import (
    ProductionDecision,
    ProductionDecisionEngine,
)
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstructionEngine,
    PortfolioTarget,
)
from personal_alpha_terminal.quant_engine.portfolio.trades import (
    TradeEvidence,
    TradeGenerator,
    TradeProposal,
)
from personal_alpha_terminal.quant_engine.risk.budget import (
    DynamicRiskBudget,
    PortfolioRiskState,
    RegimeRiskInput,
)
from personal_alpha_terminal.quant_engine.risk.model import (
    AssetRiskMetadata,
    PortfolioRiskModel,
    RiskModelEstimate,
)
from personal_alpha_terminal.quant_engine.risk.stress import (
    PortfolioStressReport,
    StressRiskConfig,
    StressStatus,
    evaluate_portfolio_stress,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchPurpose,
)


class ProductionPipelineStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class PipelineStage:
    name: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class DailyQuantInput:
    authorization: ResearchDataAuthorization
    decision_time: datetime
    alpha_signals: tuple[AlphaSignal, ...]
    returns: pd.DataFrame
    benchmark_returns: pd.Series
    risk_metadata: tuple[AssetRiskMetadata, ...]
    current_weights: dict[str, float]
    portfolio_value: float
    portfolio_risk_state: PortfolioRiskState
    regime: RegimeRiskInput | None
    pit_valid: bool
    universe_snapshot_id: str | None
    data_quality: str


@dataclass(frozen=True, slots=True)
class DailyQuantOutput:
    status: ProductionPipelineStatus
    stages: tuple[PipelineStage, ...]
    risk: RiskModelEstimate | None
    target: PortfolioTarget | None
    trades: tuple[TradeProposal, ...]
    decision: ProductionDecision | None
    blockers: tuple[str, ...]
    stress: PortfolioStressReport | None = None


class DailyQuantPipeline:
    """Deterministic production chain. It has no AI, UI or broker dependency."""

    def __init__(
        self,
        *,
        risk_model: PortfolioRiskModel | None = None,
        construction: PortfolioConstructionEngine | None = None,
        risk_budget: DynamicRiskBudget | None = None,
        cost_model: TransactionCostModel | None = None,
        stress_config: StressRiskConfig | None = None,
        operational_mode: bool = False,
    ) -> None:
        self.cost_model = cost_model or TransactionCostModel()
        self.risk_model = risk_model or PortfolioRiskModel()
        self.construction = construction or PortfolioConstructionEngine(
            cost_model=self.cost_model,
            operational_mode=operational_mode,
        )
        self.risk_budget = risk_budget or DynamicRiskBudget()
        self.trade_generator = TradeGenerator(self.cost_model)
        self.decision_engine = ProductionDecisionEngine()
        self.stress_config = stress_config or StressRiskConfig()
        self.operational_mode = operational_mode

    def run(self, inputs: DailyQuantInput) -> DailyQuantOutput:
        stages: list[PipelineStage] = []
        blockers: list[str] = []
        if inputs.decision_time.tzinfo is None:
            raise ValueError("daily decision_time must be timezone-aware")
        if not inputs.authorization.permits(ResearchPurpose.PORTFOLIO_DECISION):
            blockers.extend(inputs.authorization.decision.blockers)
            stages.append(PipelineStage("Data Quality Gate", "BLOCKED", "; ".join(blockers)))
            return DailyQuantOutput(
                ProductionPipelineStatus.BLOCKED,
                tuple(stages),
                None,
                None,
                (),
                None,
                tuple(blockers),
            )
        stages.append(PipelineStage("Data Quality Gate", "VALID", inputs.data_quality))
        if not inputs.pit_valid or not inputs.universe_snapshot_id:
            blockers.append("PIT validation or historical universe snapshot is missing")
            stages.append(PipelineStage("PIT Universe", "BLOCKED", blockers[-1]))
            return DailyQuantOutput(
                ProductionPipelineStatus.BLOCKED,
                tuple(stages),
                None,
                None,
                (),
                None,
                tuple(blockers),
            )
        stages.append(PipelineStage("PIT Universe", "VALID", inputs.universe_snapshot_id))
        if inputs.data_quality not in {"VALID", "CERTIFIED"}:
            blockers.append("daily input data quality is not valid for portfolio decisions")
            stages.append(PipelineStage("Point-in-Time Inputs", "BLOCKED", blockers[-1]))
            return DailyQuantOutput(
                ProductionPipelineStatus.BLOCKED,
                tuple(stages),
                None,
                None,
                (),
                None,
                tuple(blockers),
            )
        returns_available = _history_is_available(inputs.returns, inputs.decision_time)
        benchmark_available = _history_is_available(
            inputs.benchmark_returns, inputs.decision_time
        )
        if not returns_available or not benchmark_available:
            blockers.append("risk history contains observations after decision_time")
            stages.append(PipelineStage("Point-in-Time Inputs", "BLOCKED", blockers[-1]))
            return DailyQuantOutput(
                ProductionPipelineStatus.BLOCKED,
                tuple(stages),
                None,
                None,
                (),
                None,
                tuple(blockers),
            )
        stages.append(PipelineStage("Point-in-Time Inputs", "VALID", "no future observations"))
        approved_alpha = UnifiedAlphaEngine().for_operational_decision(
            inputs.alpha_signals, decision_time=inputs.decision_time
        )
        if not approved_alpha:
            blockers.append(
                "STRATEGY_NOT_PRODUCTION_APPROVED: no immutable approval backed by "
                "locked OOS, PIT, survivorship-controlled and after-cost evidence"
            )
            stages.append(PipelineStage("Alpha Signals", "BLOCKED", blockers[-1]))
            return DailyQuantOutput(
                ProductionPipelineStatus.BLOCKED,
                tuple(stages),
                None,
                None,
                (),
                None,
                tuple(blockers),
            )
        if not self.operational_mode and any(
            item.validation_status is AlphaValidationStatus.PROVISIONAL_OPERATIONAL_APPROVED
            for item in approved_alpha
        ):
            blockers.append(
                "provisional operational signals are not allowed without an "
                "explicit operational policy"
            )
            stages.append(PipelineStage("Alpha Signals", "BLOCKED", blockers[-1]))
            return DailyQuantOutput(
                ProductionPipelineStatus.BLOCKED,
                tuple(stages),
                None,
                None,
                (),
                None,
                tuple(blockers),
            )
        stages.append(
            PipelineStage(
                "Alpha Signals",
                "VALID",
                (
                    f"{len(approved_alpha)} provisional operational signals"
                    if self.operational_mode
                    else f"{len(approved_alpha)} approved signals"
                ),
            )
        )
        try:
            risk = self.risk_model.fit(
                inputs.returns,
                metadata=inputs.risk_metadata,
                benchmark_returns=inputs.benchmark_returns,
            )
        except (ArithmeticError, FloatingPointError, ValueError) as error:
            blockers.append(f"risk model failed safely: {error}")
            stages.append(PipelineStage("Risk Model", "BLOCKED", blockers[-1]))
            return DailyQuantOutput(
                ProductionPipelineStatus.BLOCKED,
                tuple(stages),
                None,
                None,
                (),
                None,
                tuple(blockers),
            )
        if not risk.valid_for_optimization:
            blockers.extend(risk.limitations)
            stages.append(PipelineStage("Risk Model", "BLOCKED", "; ".join(risk.limitations)))
            return DailyQuantOutput(
                ProductionPipelineStatus.BLOCKED,
                tuple(stages),
                risk,
                None,
                (),
                None,
                tuple(blockers),
            )
        stages.append(PipelineStage("Risk Model", risk.status.value, risk.model_version))
        budget = self.risk_budget.evaluate(
            regime=inputs.regime,
            state=inputs.portfolio_risk_state,
            configured_target_volatility=(
                self.construction.constraints.target_annualized_volatility
            ),
        )
        stages.append(PipelineStage("Risk Budget", "VALID", "; ".join(budget.reasons) or "base"))
        try:
            target = self.construction.construct(
                authorization=inputs.authorization,
                alpha_signals=approved_alpha,
                risk=risk,
                current_weights=inputs.current_weights,
                portfolio_value=inputs.portfolio_value,
                decision_time=inputs.decision_time,
                risk_budget=budget,
            )
        except (ArithmeticError, FloatingPointError, ValueError) as error:
            blockers.append(f"portfolio construction failed safely: {error}")
            stages.append(PipelineStage("Portfolio Construction", "BLOCKED", blockers[-1]))
            return DailyQuantOutput(
                ProductionPipelineStatus.BLOCKED,
                tuple(stages),
                risk,
                None,
                (),
                None,
                tuple(blockers),
            )
        if not target.operational_approved:
            blockers.extend(target.blockers)
            stages.append(PipelineStage("Portfolio Construction", "BLOCKED", "; ".join(blockers)))
            return DailyQuantOutput(
                ProductionPipelineStatus.BLOCKED,
                tuple(stages),
                risk,
                target,
                (),
                None,
                tuple(blockers),
            )
        stages.append(
            PipelineStage(
                "Portfolio Construction",
                (
                    "PROVISIONAL_OPERATIONAL_APPROVED"
                    if self.operational_mode
                    else "PRODUCTION_APPROVED"
                ),
                target.model_version,
            )
        )
        target_vector = np.asarray(
            [target.target_weights.get(symbol, 0.0) for symbol in risk.symbols], dtype=float
        )
        aligned_target_returns = inputs.returns.loc[:, list(risk.symbols)].dropna(how="any")
        stress_returns = tuple((aligned_target_returns.to_numpy() @ target_vector).tolist())
        try:
            stress = evaluate_portfolio_stress(
                weights=target.target_weights,
                portfolio_returns=stress_returns,
                risk=risk,
                portfolio_value=inputs.portfolio_value,
                maximum_adv_participation=self.cost_model.config.maximum_adv_participation,
                config=self.stress_config,
            )
        except (ArithmeticError, ValueError) as error:
            blockers.append(f"stress evaluation failed safely: {error}")
            stages.append(PipelineStage("Stress Risk", "BLOCKED", blockers[-1]))
            return DailyQuantOutput(
                ProductionPipelineStatus.BLOCKED,
                tuple(stages),
                risk,
                target,
                (),
                None,
                tuple(blockers),
            )
        stages.append(
            PipelineStage(
                "Stress Risk",
                stress.status.value,
                "; ".join((*stress.hard_failures, *stress.warnings)) or stress.model_version,
            )
        )
        if stress.status in {StressStatus.BLOCKED, StressStatus.NOT_VALIDATED}:
            reason = (
                "STRESS_NOT_PRODUCTION_VALIDATED"
                if stress.status is StressStatus.NOT_VALIDATED
                else f"stress veto: {', '.join(stress.hard_failures)}"
            )
            blockers.append(reason)
            return DailyQuantOutput(
                ProductionPipelineStatus.BLOCKED,
                tuple(stages),
                risk,
                target,
                (),
                None,
                tuple(blockers),
                stress,
            )
        evidence = _trade_evidence(approved_alpha)
        risk_contribution = _risk_contributions(target, risk)
        try:
            trades = self.trade_generator.generate(
                target=target,
                current_weights=inputs.current_weights,
                portfolio_value=inputs.portfolio_value,
                evidence=evidence,
                risk_contribution=risk_contribution,
                average_daily_dollar_volume=risk.average_daily_dollar_volume,
                minimum_trade_weight=self.construction.constraints.minimum_rebalance_weight,
            )
        except (ArithmeticError, ValueError) as error:
            blockers.append(f"trade generation failed safely: {error}")
            stages.append(PipelineStage("Trade Generator", "BLOCKED", blockers[-1]))
            return DailyQuantOutput(
                ProductionPipelineStatus.BLOCKED,
                tuple(stages),
                risk,
                target,
                (),
                None,
                tuple(blockers),
            )
        stages.append(PipelineStage("Trade Generator", "VALID", f"{len(trades)} proposals"))
        decision = self.decision_engine.generate(
            authorization=inputs.authorization,
            target=target,
            current_weights=inputs.current_weights,
            proposals=trades,
            as_of=inputs.decision_time,
        )
        stages.append(
            PipelineStage(
                "Daily Decision",
                decision.status.value,
                "manual review required; automatic execution disabled",
            )
        )
        return DailyQuantOutput(
            ProductionPipelineStatus.READY,
            tuple(stages),
            risk,
            target,
            trades,
            decision,
            (),
            stress,
        )


def _trade_evidence(signals: tuple[AlphaSignal, ...]) -> dict[str, TradeEvidence]:
    grouped: dict[str, list[AlphaSignal]] = {}
    for signal in signals:
        grouped.setdefault(signal.symbol, []).append(signal)
    output: dict[str, TradeEvidence] = {}
    for symbol, items in grouped.items():
        calibrated = all(item.confidence_calibrated for item in items)
        confidence = (
            sum(item.confidence for item in items) / len(items)
            if calibrated
            else None
        )
        expected = sum(item.expected_excess_return for item in items) / len(items)
        horizon = max(1, round(sum(item.horizon for item in items) / len(items)))
        output[symbol] = TradeEvidence(
            expected,
            confidence,
            horizon,
            tuple(f"{item.signal_type}:{item.model_version}" for item in items),
            tuple(
                f"{item.signal_type} expires {item.valid_until.isoformat()}"
                for item in items
                if item.confidence < 0.75
            ),
            calibrated,
        )
    return output


def _risk_contributions(
    target: PortfolioTarget, risk: RiskModelEstimate
) -> dict[str, float]:
    weights = np.array([target.target_weights.get(symbol, 0.0) for symbol in risk.symbols])
    marginal = risk.annualized_covariance @ weights
    variance = float(weights @ marginal)
    if variance <= 0:
        return {symbol: 0.0 for symbol in risk.symbols}
    return {
        symbol: float(weights[index] * marginal[index] / variance)
        for index, symbol in enumerate(risk.symbols)
    }


def _history_is_available(
    history: pd.DataFrame | pd.Series, decision_time: datetime
) -> bool:
    if history.empty or not isinstance(history.index, pd.DatetimeIndex):
        return False
    latest = history.index.max()
    if latest is pd.NaT:
        return False
    if latest.tzinfo is None:
        return bool(latest.date() <= decision_time.date())
    return bool(latest.to_pydatetime() <= decision_time)
