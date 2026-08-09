from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from math import floor

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.data.us_market.session import CertifiedUSSessionService
from personal_alpha_terminal.models import (
    Price,
    QuantDecisionRecommendation,
    QuantDecisionRun,
    SecurityMaster,
)
from personal_alpha_terminal.quant_engine.costs import TransactionCostModel
from personal_alpha_terminal.quant_engine.input_assembler import (
    AssembledDailyInput,
    AssembledResearchInput,
    PortfolioInputPosition,
    ProductionDailyQuantInputAssembler,
)
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstructionEngine,
    PortfolioTarget,
)
from personal_alpha_terminal.quant_engine.portfolio.trades import TradeAction, TradeProposal
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantOutput,
    DailyQuantPipeline,
    PipelineStage,
    ProductionPipelineStatus,
)
from personal_alpha_terminal.quant_engine.risk.budget import PortfolioRiskState
from personal_alpha_terminal.quant_engine.risk.model import PortfolioRiskModel, RiskModelEstimate
from personal_alpha_terminal.quant_engine.risk.stress import (
    PortfolioStressReport,
    StressRiskConfig,
)
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    StrategyFactorSnapshot,
)
from personal_alpha_terminal.quant_engine.validation_artifacts import (
    PortfolioValidationIdentity,
    ValidationArtifactRegistry,
)


@dataclass(frozen=True, slots=True)
class TodayRecommendation:
    recommendation_id: str
    symbol: str
    action: str
    current_weight: float
    target_weight: float
    target_delta: float
    estimated_quantity: int
    expected_cost: float
    expected_alpha: float
    confidence: float
    risk_reason: str
    model_version: str
    data_version: str
    earliest_execution_time: datetime
    expiry: datetime
    estimated_value: float = 0.0
    risk_contribution: float = 0.0
    reason: str = ""
    data_quality: str = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class TodayResult:
    run_id: int
    decision_time: datetime
    market_session: str
    data_freshness: str
    status: str
    data_certification: str
    model_status: str
    portfolio_status: str
    risk_regime: str
    gross_target: float | None
    cash_target: float | None
    recommendations: tuple[TodayRecommendation, ...]
    no_rebalance_reason: str | None
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    data_hash: str
    model_hash: str
    config_hash: str
    pipeline_stages: tuple[PipelineStage, ...] = ()
    factors: tuple[StrategyFactorSnapshot, ...] = ()
    risk: RiskModelEstimate | None = None
    target: PortfolioTarget | None = None
    trades: tuple[TradeProposal, ...] = ()
    portfolio_value: float | None = None
    current_weights: dict[str, float] | None = None
    data_cutoff: datetime | None = None
    universe_count: int = 0
    source_ids: tuple[str, ...] = ()
    disabled_components: tuple[str, ...] = ()
    benchmark_symbol: str = "SPY"
    benchmark_observations: int = 0
    benchmark_period_return: float | None = None
    benchmark_annualized_volatility: float | None = None
    portfolio_positions: tuple[PortfolioInputPosition, ...] = ()
    cash_balance: float | None = None
    configured_target_volatility: float | None = None
    identity_hashes: dict[str, str] | None = None
    model_approval_hash: str = "UNAVAILABLE"
    probability_calibration_status: str = "PROBABILITY_NOT_CALIBRATED"
    stress: PortfolioStressReport | None = None
    risk_state: PortfolioRiskState | None = None


class ProductionDailyWorkflow:
    """Headless production daily path; failures persist diagnosis, never actions."""

    def __init__(
        self, session: Session, effective_config: EffectiveRuntimeConfig | None = None
    ) -> None:
        self.session = session
        self.effective_config = effective_config or EffectiveRuntimeConfig()
        self.assembler = ProductionDailyQuantInputAssembler(
            session, effective_config=self.effective_config
        )
        self.pipeline = self._pipeline(None)
        self.sessions = CertifiedUSSessionService(session)
        self.validation_registry = ValidationArtifactRegistry(
            self.effective_config.validation_artifact_dir
        )

    def _pipeline(self, validation_id: str | None) -> DailyQuantPipeline:
        costs = TransactionCostModel(self.effective_config.transaction_cost)
        construction = PortfolioConstructionEngine(
            constraints=replace(
                self.effective_config.portfolio_constraints,
                model_validation_id=validation_id,
            ),
            cost_model=costs,
        )
        stress_config = StressRiskConfig(
            **{
                **asdict(self.effective_config.stress_risk),
                "production_validated": validation_id is not None,
                "validation_id": validation_id,
            }
        )
        return DailyQuantPipeline(
            risk_model=PortfolioRiskModel(self.effective_config.risk_model),
            construction=construction,
            cost_model=costs,
            stress_config=stress_config,
        )

    def run(self, *, portfolio_id: int | None, decision_time: datetime) -> TodayResult:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        try:
            research = self.assembler.assemble_research(
                decision_time=decision_time,
            )
        except (ArithmeticError, LookupError, RuntimeError, ValueError) as error:
            blocker = str(error) or type(error).__name__
            run_id = 0
            if portfolio_id is not None:
                run_id = self._persist_blocked(
                    portfolio_id=portfolio_id,
                    decision_time=decision_time,
                    blockers=(blocker,),
                ).id
            return TodayResult(
                run_id=run_id,
                decision_time=decision_time,
                market_session="UNKNOWN",
                data_freshness="UNAVAILABLE",
                status="BLOCKED",
                data_certification="BLOCKED",
                model_status="NOT_READY",
                portfolio_status=("NOT_INITIALIZED" if portfolio_id is None else "UNCHANGED"),
                risk_regime="SCORE_UNAVAILABLE",
                gross_target=None,
                cash_target=None,
                recommendations=(),
                no_rebalance_reason=None,
                blockers=(blocker,),
                warnings=(),
                data_hash="UNAVAILABLE",
                model_hash="UNAVAILABLE",
                config_hash="UNAVAILABLE",
                pipeline_stages=self._blocked_research_stages(blocker),
            )

        if portfolio_id is None:
            blocker = "PORTFOLIO NOT INITIALIZED; run portfolio-init or portfolio-import"
            return self._research_only_result(research, blocker)

        try:
            assembled = self.assembler.complete_with_portfolio(
                research,
                portfolio_id=portfolio_id,
            )
            portfolio_approval = self.validation_registry.matching_portfolio_approval(
                PortfolioValidationIdentity(
                    alpha_model_version=(
                        f"{self.assembler.strategy.model_id}:{self.assembler.strategy.version}"
                    ),
                    alpha_data_version=research.data_version,
                    strategy_parameter_hash=research.parameter_fingerprint,
                    portfolio_constraint_hash=self.effective_config.portfolio_constraint_hash,
                    risk_model_hash=self.effective_config.risk_model_hash,
                    cost_model_hash=self.effective_config.cost_model_hash,
                    runtime_config_hash=self.effective_config.runtime_config_hash,
                    benchmark_definition=research.benchmark_symbol,
                )
            )
            self.pipeline = self._pipeline(
                portfolio_approval.validation_id if portfolio_approval is not None else None
            )
            output = self.pipeline.run(assembled.inputs)
        except (ArithmeticError, LookupError, RuntimeError, ValueError) as error:
            blocker = str(error) or type(error).__name__
            run = self._persist_blocked(
                portfolio_id=portfolio_id,
                decision_time=decision_time,
                blockers=(blocker,),
            )
            return TodayResult(
                run_id=run.id,
                decision_time=decision_time,
                market_session="UNKNOWN",
                data_freshness="UNAVAILABLE",
                status="BLOCKED",
                data_certification="BLOCKED",
                model_status="NOT_READY",
                portfolio_status="UNCHANGED",
                risk_regime="SCORE_UNAVAILABLE",
                gross_target=None,
                cash_target=None,
                recommendations=(),
                no_rebalance_reason=None,
                blockers=(blocker,),
                warnings=(),
                data_hash="UNAVAILABLE",
                model_hash="UNAVAILABLE",
                config_hash="UNAVAILABLE",
                pipeline_stages=(*self._research_stages(research), PipelineStage(
                    "Portfolio Construction", "BLOCKED", blocker
                )),
                factors=research.factors,
                data_cutoff=research.data_cutoff,
                universe_count=research.universe_count,
                source_ids=research.source_ids,
                disabled_components=research.disabled_components,
                benchmark_symbol=research.benchmark_symbol,
                benchmark_observations=research.benchmark_observations,
                benchmark_period_return=research.benchmark_period_return,
                benchmark_annualized_volatility=research.benchmark_annualized_volatility,
            )

        inputs = assembled.inputs
        if inputs.authorization.evidence is None:
            raise ValueError("production authorization is missing immutable data evidence")
        evidence = inputs.authorization.evidence
        data_version = (
            output.target.data_version if output.target is not None else "UNAVAILABLE"
        )
        model_version = (
            output.target.model_version if output.target is not None else "UNAVAILABLE"
        )
        fingerprint = _fingerprint(
            {
                "portfolio_id": portfolio_id,
                "decision_time": decision_time.isoformat(),
                "data_version": data_version,
                "model_version": model_version,
                "parameters": assembled.parameter_fingerprint,
            }
        )
        existing = self.session.scalar(
            select(QuantDecisionRun).where(
                QuantDecisionRun.portfolio_id == portfolio_id,
                QuantDecisionRun.as_of_time == decision_time,
                QuantDecisionRun.input_fingerprint == fingerprint,
            )
        )
        if existing is not None:
            return self._result_from_record(
                existing,
                assembled.parameter_fingerprint,
                assembled=assembled,
                output=output,
            )

        if output.status is ProductionPipelineStatus.BLOCKED or output.decision is None:
            run = QuantDecisionRun(
                portfolio_id=portfolio_id,
                as_of_time=decision_time,
                status="blocked",
                gate_status="BLOCKED",
                authorization_id=inputs.authorization.authorization_id,
                data_version=data_version,
                model_version=model_version,
                input_fingerprint=fingerprint,
                source_ids=list(evidence.source_ids),
                blockers=list(output.blockers),
            )
            self.session.add(run)
            self.session.flush()
            return self._result_from_record(
                run,
                assembled.parameter_fingerprint,
                assembled=assembled,
                output=output,
            )

        execution = self.sessions.next_tradable_open(decision_time=decision_time)
        target = output.target
        assert target is not None
        actionable = [item for item in output.trades if item.action is not TradeAction.HOLD]
        run = QuantDecisionRun(
            portfolio_id=portfolio_id,
            as_of_time=decision_time,
            status="generated" if actionable else "no_decision",
            gate_status="APPROVED",
            authorization_id=inputs.authorization.authorization_id,
            data_version=target.data_version,
            model_version=target.model_version,
            input_fingerprint=fingerprint,
            source_ids=list(evidence.source_ids),
            blockers=[],
        )
        self.session.add(run)
        self.session.flush()
        for proposal in output.trades:
            security = self.session.scalar(
                select(SecurityMaster).where(SecurityMaster.symbol == proposal.ticker)
            )
            if security is None:
                raise ValueError(f"target security is missing: {proposal.ticker}")
            price = self.session.scalar(
                select(Price)
                .where(
                    Price.stock_id == security.id,
                    Price.price_type == "unadjusted_ohlcv",
                    Price.available_time <= decision_time,
                )
                .order_by(Price.trade_date.desc(), Price.id.desc())
                .limit(1)
            )
            if price is None or float(price.close) <= 0:
                raise ValueError(f"target security lacks a raw reference price: {proposal.ticker}")
            action = "ADD" if proposal.action is TradeAction.INCREASE else proposal.action.value
            quantity = floor(proposal.estimated_trade_value / float(price.close))
            recommendation_id = f"{fingerprint[:20]}:{security.canonical_code}"
            run.recommendations.append(
                QuantDecisionRecommendation(
                    recommendation_id=recommendation_id,
                    stock_id=security.id,
                    action=action,
                    current_weight=Decimal(str(proposal.current_weight)),
                    target_weight=Decimal(str(proposal.target_weight)),
                    quant_score=Decimal("0"),
                    confidence_score=Decimal(str(proposal.confidence * 100)),
                    component_scores={
                        "expected_alpha": proposal.expected_alpha,
                        "risk_contribution": proposal.risk_contribution,
                        "estimated_cost": proposal.estimated_cost,
                    },
                    rationale=[proposal.reason, *proposal.primary_evidence],
                    risk_factors=list(proposal.counter_evidence),
                    evidence_grade="MODEL_APPROVED",
                    sample_size=0,
                    source_ids=list(evidence.source_ids),
                    reference_price=price.close,
                    suggested_shares=quantity,
                    earliest_execution_time=execution.open_time,
                    expires_at=execution.open_time + timedelta(days=7),
                    review_status="pending",
                )
            )
        self.session.flush()
        return self._result_from_record(
            run,
            assembled.parameter_fingerprint,
            assembled=assembled,
            output=output,
        )

    @staticmethod
    def _research_stages(research: AssembledResearchInput) -> tuple[PipelineStage, ...]:
        return (
            PipelineStage("Data Quality Gate", "VALID", "CERTIFIED"),
            PipelineStage("PIT Universe", "VALID", research.universe_snapshot_id),
            PipelineStage("Point-in-Time Inputs", "VALID", "no future observations"),
            PipelineStage(
                "Feature Engine",
                "VALID",
                f"{len(research.factors)} PIT feature rows",
            ),
            PipelineStage(
                "Factor Engine",
                "VALID",
                f"{len(research.factors)} cross-sectional factor rows",
            ),
            PipelineStage(
                "Alpha Signals",
                "VALID",
                f"{len(research.alpha_signals)} model-approved signals",
            ),
        )

    @staticmethod
    def _blocked_research_stages(blocker: str) -> tuple[PipelineStage, ...]:
        lowered = blocker.lower()
        if "universe" in lowered:
            return (PipelineStage("PIT Universe", "BLOCKED", blocker),)
        if "total-return" in lowered or "point-in-time" in lowered or "pit" in lowered:
            return (PipelineStage("Point-in-Time Inputs", "BLOCKED", blocker),)
        if "alpha" in lowered or "model" in lowered:
            return (PipelineStage("Alpha Signals", "BLOCKED", blocker),)
        return (PipelineStage("Data Quality Gate", "BLOCKED", blocker),)

    def _research_only_result(
        self, research: AssembledResearchInput, blocker: str
    ) -> TodayResult:
        return TodayResult(
            run_id=0,
            decision_time=research.decision_time,
            market_session="POST_CLOSE_DECISION",
            data_freshness="CERTIFIED_AS_OF_DECISION",
            status="BLOCKED",
            data_certification="APPROVED",
            model_status="APPROVED",
            portfolio_status="NOT_INITIALIZED",
            risk_regime="SCORE_UNAVAILABLE",
            gross_target=None,
            cash_target=None,
            recommendations=(),
            no_rebalance_reason=None,
            blockers=(blocker,),
            warnings=(),
            data_hash=research.data_version,
            model_hash=self.assembler.strategy.version,
            config_hash=self.effective_config.canonical_run_config_hash,
            pipeline_stages=(*self._research_stages(research), PipelineStage(
                "Portfolio Construction", "BLOCKED", blocker
            )),
            factors=research.factors,
            portfolio_value=None,
            current_weights=None,
            data_cutoff=research.data_cutoff,
            universe_count=research.universe_count,
            source_ids=research.source_ids,
            disabled_components=research.disabled_components,
            benchmark_symbol=research.benchmark_symbol,
            benchmark_observations=research.benchmark_observations,
            benchmark_period_return=research.benchmark_period_return,
            benchmark_annualized_volatility=research.benchmark_annualized_volatility,
            portfolio_positions=(),
            cash_balance=None,
            configured_target_volatility=None,
            identity_hashes=self._identity_hashes(research.data_version),
        )

    def _persist_blocked(
        self,
        *,
        portfolio_id: int,
        decision_time: datetime,
        blockers: tuple[str, ...],
    ) -> QuantDecisionRun:
        fingerprint = _fingerprint(
            {
                "portfolio_id": portfolio_id,
                "decision_time": decision_time.isoformat(),
                "blockers": blockers,
            }
        )
        existing = self.session.scalar(
            select(QuantDecisionRun).where(
                QuantDecisionRun.portfolio_id == portfolio_id,
                QuantDecisionRun.as_of_time == decision_time,
                QuantDecisionRun.input_fingerprint == fingerprint,
            )
        )
        if existing is not None:
            return existing
        run = QuantDecisionRun(
            portfolio_id=portfolio_id,
            as_of_time=decision_time,
            status="blocked",
            gate_status="BLOCKED",
            authorization_id=None,
            data_version="UNAVAILABLE",
            model_version="UNAVAILABLE",
            input_fingerprint=fingerprint,
            source_ids=[],
            blockers=list(blockers),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def _result_from_record(
        self,
        run: QuantDecisionRun,
        config_hash: str,
        *,
        assembled: AssembledDailyInput | None = None,
        output: DailyQuantOutput | None = None,
    ) -> TodayResult:
        recommendations = tuple(
            TodayRecommendation(
                recommendation_id=item.recommendation_id,
                symbol=item.stock.symbol,
                action=item.action,
                current_weight=float(item.current_weight),
                target_weight=float(item.target_weight),
                target_delta=float(item.target_weight - item.current_weight),
                estimated_quantity=item.suggested_shares,
                expected_cost=float(item.component_scores.get("estimated_cost", 0.0)),
                expected_alpha=float(item.component_scores.get("expected_alpha", 0.0)),
                confidence=float(item.confidence_score) / 100,
                risk_reason="; ".join(item.risk_factors),
                model_version=run.model_version,
                data_version=run.data_version,
                earliest_execution_time=item.earliest_execution_time,
                expiry=item.expires_at,
                estimated_value=abs(
                    float(item.target_weight - item.current_weight)
                    * float(assembled.inputs.portfolio_value)
                )
                if assembled is not None
                else 0.0,
                risk_contribution=float(
                    item.component_scores.get("risk_contribution", 0.0)
                ),
                reason="; ".join(item.rationale),
                data_quality=(
                    next(
                        (
                            proposal.data_quality
                            for proposal in output.trades
                            if proposal.ticker == item.stock.symbol
                        ),
                        "UNAVAILABLE",
                    )
                    if output is not None
                    else "UNAVAILABLE"
                ),
            )
            for item in run.recommendations
        )
        gross = sum(item.target_weight for item in recommendations)
        no_rebalance = None
        if run.status == "no_decision":
            no_rebalance = "all target differences are inside the validated no-trade band"
        return TodayResult(
            run_id=run.id,
            decision_time=run.as_of_time,
            market_session="POST_CLOSE_DECISION",
            data_freshness=(
                "CERTIFIED_AS_OF_DECISION"
                if run.gate_status == "APPROVED"
                else "UNAVAILABLE"
            ),
            status=run.status.upper(),
            data_certification=run.gate_status,
            model_status="APPROVED" if run.gate_status == "APPROVED" else "NOT_READY",
            portfolio_status="TARGET_COMPUTED" if run.gate_status == "APPROVED" else "UNCHANGED",
            risk_regime="SCORE_UNAVAILABLE",
            gross_target=gross if run.gate_status == "APPROVED" else None,
            cash_target=1 - gross if run.gate_status == "APPROVED" else None,
            recommendations=recommendations,
            no_rebalance_reason=no_rebalance,
            blockers=tuple(run.blockers),
            warnings=(),
            data_hash=run.data_version,
            model_hash=run.model_version,
            config_hash=self.effective_config.canonical_run_config_hash,
            pipeline_stages=output.stages if output is not None else (),
            factors=getattr(assembled, "factors", ()),
            risk=output.risk if output is not None else None,
            target=output.target if output is not None else None,
            trades=output.trades if output is not None else (),
            portfolio_value=(
                float(assembled.inputs.portfolio_value)
                if assembled is not None
                else None
            ),
            current_weights=(
                dict(assembled.inputs.current_weights)
                if assembled is not None
                else None
            ),
            data_cutoff=getattr(assembled, "data_cutoff", None),
            universe_count=int(getattr(assembled, "universe_count", 0)),
            source_ids=tuple(getattr(assembled, "source_ids", ())),
            disabled_components=tuple(
                getattr(assembled, "disabled_components", ())
            ),
            benchmark_symbol=str(getattr(assembled, "benchmark_symbol", "SPY")),
            benchmark_observations=int(
                getattr(assembled, "benchmark_observations", 0)
            ),
            benchmark_period_return=getattr(
                assembled, "benchmark_period_return", None
            ),
            benchmark_annualized_volatility=getattr(
                assembled, "benchmark_annualized_volatility", None
            ),
            portfolio_positions=tuple(
                getattr(assembled, "portfolio_positions", ())
            ),
            cash_balance=getattr(assembled, "cash_balance", None),
            configured_target_volatility=(
                self.pipeline.construction.constraints.target_annualized_volatility
                if output is not None
                else None
            ),
            identity_hashes=self._identity_hashes(run.data_version),
            model_approval_hash=(
                output.target.model_validation_id
                if output is not None and output.target is not None
                else "UNAVAILABLE"
            ),
            probability_calibration_status=(
                "CALIBRATED_LOCKED_OOS"
                if any(item.confidence_calibrated for item in assembled.inputs.alpha_signals)
                else "PROBABILITY_NOT_CALIBRATED"
            ) if assembled is not None else "PROBABILITY_NOT_CALIBRATED",
            stress=output.stress if output is not None else None,
            risk_state=(assembled.inputs.portfolio_risk_state if assembled is not None else None),
        )

    def _identity_hashes(self, data_version: str) -> dict[str, str]:
        return {
            "runtime_config_hash": self.effective_config.runtime_config_hash,
            "strategy_parameter_hash": self.effective_config.strategy_parameter_hash,
            "data_version_hash": data_version,
            "portfolio_constraint_hash": self.effective_config.portfolio_constraint_hash,
            "risk_model_hash": self.effective_config.risk_model_hash,
            "cost_model_hash": self.effective_config.cost_model_hash,
            "canonical_run_config_hash": self.effective_config.canonical_run_config_hash,
        }


def _fingerprint(payload: dict[str, object]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
