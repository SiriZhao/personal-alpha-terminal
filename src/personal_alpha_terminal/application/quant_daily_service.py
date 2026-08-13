from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from math import floor

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.application.operational_readiness import (
    OperationalPolicy,
    OperationalPolicyDecision,
    OperationalPolicyStore,
    OperationalReadiness,
    resolve_current_operational_identity,
)
from personal_alpha_terminal.application.regime_link import (
    REGIME_UNAVAILABLE,
    RegimeLinkResult,
    latest_regime_link,
)
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.data.us_market.session import CertifiedUSSessionService
from personal_alpha_terminal.models import (
    Price,
    QuantDecisionRecommendation,
    QuantDecisionRun,
    SecurityMaster,
)
from personal_alpha_terminal.quant_engine.alpha import AlphaSignal
from personal_alpha_terminal.quant_engine.benchmark import BenchmarkEvidence
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
from personal_alpha_terminal.quant_engine.probability_overlay import ProbabilityOverlayEffect
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
    confidence: float | None
    risk_reason: str
    model_version: str
    data_version: str
    earliest_execution_time: datetime
    expiry: datetime
    estimated_value: float = 0.0
    risk_contribution: float = 0.0
    reason: str = ""
    data_quality: str = "UNAVAILABLE"
    confidence_source: str = "NOT_CALIBRATED"


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
    risk_regime_detail: str = ""
    benchmark_evidences: tuple[BenchmarkEvidence, ...] = ()
    strategy_version: str = 'UNAVAILABLE'
    production_approval_artifact_id: str = 'NOT_APPROVED'
    portfolio_validation_artifact_id: str = 'NOT_APPROVED'
    probability_artifact_id: str = 'OPTIONAL_UNAVAILABLE'
    universe_snapshot_id: str = 'UNAVAILABLE'
    portfolio_snapshot_id: str = 'NOT_INITIALIZED'
    universe_evidence: dict[str, object] = field(default_factory=dict)
    probability_overlay_active: bool = False
    probability_overlay_state: str = "RESEARCH_ONLY"
    probability_overlay_reason: str = "PROBABILITY_ARTIFACT_MISSING"
    probability_overlay_effects: tuple[ProbabilityOverlayEffect, ...] = ()
    probability_counterfactual: dict[str, dict[str, object]] = field(default_factory=dict)
    operational_approval_artifact_id: str = 'NOT_APPROVED'
    operational_readiness: str = OperationalReadiness.BLOCKED.value
    research_certification_state: str = "NOT_CERTIFIABLE"
    operational_policy_id: str = "NOT_CONFIGURED"
    operational_policy_decision: str = "BLOCK"
    operational_policy_effective: bool = False
    operational_policy_reason: str = "OPERATIONAL_POLICY_NOT_CONFIGURED"
    operational_policy_hash: str = "NOT_CONFIGURED"
    operational_policy_identity_hash: str = "NOT_CONFIGURED"
    signal_authorization_class: str = "FAIL_BLOCKING"
    signal_evidence_level: str = "DIAGNOSTIC_ONLY"
    operationally_allowed: bool = False
    operational_degraded_reason: str | None = None
    lifecycle: dict[str, object] | None = None
    lifecycle_blocked_symbols: tuple[str, ...] = ()


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
        self.operational_store = OperationalPolicyStore(
            self.effective_config.operational_policy_path
        )

    def _pipeline(
        self,
        validation_id: str | None,
        *,
        operational_mode: bool = False,
    ) -> DailyQuantPipeline:
        costs = TransactionCostModel(self.effective_config.transaction_cost)
        construction = PortfolioConstructionEngine(
            constraints=replace(
                self.effective_config.portfolio_constraints,
                model_validation_id=validation_id,
            ),
            cost_model=costs,
            operational_mode=operational_mode,
        )
        stress_config = StressRiskConfig(
            **{
                **asdict(self.effective_config.stress_risk),
                "production_validated": validation_id is not None and not operational_mode,
                "validation_id": validation_id,
                "provisional_operational": operational_mode,
            }
        )
        return DailyQuantPipeline(
            risk_model=PortfolioRiskModel(self.effective_config.risk_model),
            construction=construction,
            cost_model=costs,
            stress_config=stress_config,
            operational_mode=operational_mode,
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
                risk_regime=REGIME_UNAVAILABLE,
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
                risk_regime_detail=(
                    "REGIME OPTIONAL: research stages blocked; regime evidence not evaluated."
                ),
            )

        regime_link = latest_regime_link(
            self.session,
            self.effective_config.settings,
            decision_time=decision_time,
        )

        if portfolio_id is None:
            blocker = "PORTFOLIO NOT INITIALIZED; run portfolio-init or portfolio-import"
            return self._research_only_result(research, blocker, regime_link=regime_link)

        try:
            assembled = self.assembler.complete_with_portfolio(
                research,
                portfolio_id=portfolio_id,
                regime=regime_link.regime_input,
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
            provisional_policy = self._operational_policy(decision_time)
            if portfolio_approval is not None:
                validation_id = portfolio_approval.validation_id
                operational_mode = False
            elif provisional_policy is not None:
                validation_id = provisional_policy.policy_id
                operational_mode = True
            else:
                validation_id = None
                operational_mode = False
            self.pipeline = self._pipeline(
                validation_id,
                operational_mode=operational_mode,
            )
            output = self.pipeline.run(assembled.inputs)
            classical_output = self.pipeline.run(
                replace(
                    assembled.inputs,
                    alpha_signals=assembled.classical_alpha_signals,
                )
            )
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
                risk_regime=regime_link.display_status,
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
                risk_regime_detail=regime_link.detail,
                benchmark_evidences=research.benchmark_evidences,
                universe_evidence=research.universe_evidence,
                probability_overlay_active=research.probability_overlay_active,
                probability_overlay_state=research.probability_overlay_state,
                probability_overlay_reason=research.probability_overlay_reason,
                probability_overlay_effects=research.probability_overlay_effects,
            )

        inputs = assembled.inputs
        if inputs.authorization.evidence is None:
            raise ValueError("production authorization is missing immutable data evidence")
        evidence = inputs.authorization.evidence
        data_version = assembled.data_version
        model_version = assembled.strategy_version
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
                classical_output=classical_output,
                regime_link=regime_link,
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
                classical_output=classical_output,
                regime_link=regime_link,
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
                    confidence_score=(
                        Decimal(str(proposal.confidence * 100))
                        if proposal.confidence is not None
                        else None
                    ),
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
        self._append_forward_predictions(run, assembled)
        self._append_shadow_predictions(run, assembled)
        return self._result_from_record(
            run,
            assembled.parameter_fingerprint,
            assembled=assembled,
            output=output,
            classical_output=classical_output,
            regime_link=regime_link,
        )

    def _append_forward_predictions(
        self,
        run: QuantDecisionRun,
        assembled: AssembledDailyInput,
    ) -> None:
        """Append immutable forward predictions for approved recommendations.

        This is a historical evidence ledger only: it records what the system
        actually recommended, never a simulated fill.  Future outcomes may only
        be appended by an explicit ``forward-track append-outcome`` command;
        predictions are never mutated.
        """
        from personal_alpha_terminal.quant_engine.forward_track import (
            ForwardPrediction,
            append_prediction,
        )

        path = self.effective_config.forward_ledger_path
        for recommendation in run.recommendations:
            expected_alpha = float(
                recommendation.component_scores.get("expected_alpha", 0.0)
            )
            risk_contribution = recommendation.component_scores.get(
                "risk_contribution"
            )
            confidence = (
                float(recommendation.confidence_score)
                if recommendation.confidence_score is not None
                else None
            )
            prediction = ForwardPrediction(
                recommendation_id=recommendation.recommendation_id,
                run_id=str(run.id),
                symbol=recommendation.stock.symbol,
                as_of=run.as_of_time,
                decision_time=run.as_of_time,
                target_weight=float(recommendation.target_weight),
                expected_alpha=expected_alpha,
                probability=(confidence / 100.0 if confidence is not None else None),
                risk_contribution=(
                    float(risk_contribution)
                    if risk_contribution is not None
                    else None
                ),
                benchmark=assembled.benchmark_symbol,
                data_hash=run.data_version,
                created_at=run.as_of_time,
            )
            append_prediction(prediction, path)

    def _append_shadow_predictions(
        self,
        run: QuantDecisionRun,
        assembled: AssembledDailyInput,
    ) -> None:
        """Record what a configured challenger would recommend (SHADOW only).

        A challenger in shadow mode never changes the official recommendation,
        target, portfolio or ledger.  It only appends immutable predictions to
        the shadow ledger so a real forward comparison can accumulate.  The
        challenger must be registered in the research registry and must not be
        production-approved; anything else fails closed to no-op.
        """
        challenger_id = self.effective_config.shadow_challenger_id
        if not challenger_id:
            return
        from personal_alpha_terminal.quant_engine.alpha_engine2.research_registry import (
            ExperimentStatus,
            ResearchRegistry,
        )
        from personal_alpha_terminal.quant_engine.alpha_engine2.shadow import (
            ShadowLedger,
            ShadowPrediction,
        )

        registry = ResearchRegistry(self.effective_config.shadow_registry_path)
        experiments = registry.by_strategy(challenger_id)
        if not experiments:
            return
        # A challenger is shadow-eligible only while it is RESEARCH_ONLY (or
        # REJECTED).  A promoted challenger is handled by the normal production
        # approval path, not the shadow ledger.
        if any(
            item.status is ExperimentStatus.PROMOTED for item in experiments
        ):
            return
        coefficients = self.effective_config.shadow_coefficients or _challenger_coefficients(
            experiments[-1]
        )
        factors = assembled.factors
        if not factors:
            return
        def _challenger_alpha(factor: StrategyFactorSnapshot) -> float:
            return float(
                factor.components.get("momentum", 0.0)
                * coefficients.get("momentum_coefficient", 0.0)
                + factor.components.get("trend", 0.0)
                * coefficients.get("trend_coefficient", 0.0)
                + factor.components.get("low_volatility", 0.0)
                * coefficients.get("low_volatility_coefficient", 0.0)
            )

        ranked = sorted(factors, key=lambda item: (-_challenger_alpha(item), item.symbol))
        ledger = ShadowLedger(self.effective_config.shadow_ledger_path)
        for index, factor in enumerate(ranked[:20], start=1):
            alpha = _challenger_alpha(factor)
            recommendation = (
                "BUY"
                if alpha > 0 and factor.rank <= 10
                else "ADD"
                if alpha > 0
                else "HOLD"
            )
            prediction = ShadowPrediction(
                shadow_id=f"shadow-{run.id}-{factor.symbol}",
                run_id=str(run.id),
                decision_time=run.as_of_time,
                challenger_id=challenger_id,
                challenger_version=experiments[-1].strategy_version,
                symbol=factor.symbol,
                rank=index,
                expected_alpha=float(alpha),
                target_weight=0.0,
                recommendation=recommendation,
                data_hash=run.data_version,
                created_at=run.as_of_time,
            )
            ledger.append_prediction(prediction)

    @staticmethod
    def _research_stages(research: AssembledResearchInput) -> tuple[PipelineStage, ...]:
        approved = tuple(
            item
            for item in research.alpha_signals
            if item.operational_eligible(research.decision_time)
        )
        alpha_status = "VALID" if approved else "BLOCKED"
        provisional = any(
            item.validation_status.value == "PROVISIONAL_OPERATIONAL_APPROVED"
            for item in approved
        )
        alpha_detail = (
            (
                f"{len(approved)} PROVISIONAL_OPERATIONAL_APPROVED signals"
                if provisional
                else f"{len(approved)} PRODUCTION_APPROVED signals"
            )
            if approved
            else (
                "STRATEGY_NOT_PRODUCTION_APPROVED: no provisional operational "
                "approval or full production approval is bound to this strategy; "
                "candidates remain DIAGNOSTIC_ONLY"
            )
        )
        return (
            PipelineStage("Data Quality Gate", "VALID", "CERTIFIED"),
            PipelineStage("PIT Universe", "VALID", research.universe_snapshot_id),
            PipelineStage(
                "Broad Equity Universe",
                (
                    "VALID"
                    if research.universe_evidence.get("factor_eligible", 0)
                    else "DEGRADED"
                ),
                (
                    "listed="
                    f"{research.universe_evidence.get('raw_listed_equities', 'UNAVAILABLE')}; "
                    f"factor_eligible={research.universe_evidence.get('factor_eligible', 0)}; "
                    "survivorship="
                    f"{research.universe_evidence.get('survivorship_status', 'UNVERIFIED')}"
                ),
            ),
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
                alpha_status,
                alpha_detail,
            ),
            PipelineStage(
                "Probability Overlay",
                "VALID" if research.probability_overlay_active else "DEGRADED",
                (
                    f"{research.probability_overlay_state}; "
                    f"active={research.probability_overlay_active}; "
                    f"reason={research.probability_overlay_reason}"
                ),
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
        self,
        research: AssembledResearchInput,
        blocker: str,
        *,
        regime_link: RegimeLinkResult | None = None,
    ) -> TodayResult:
        link = regime_link or RegimeLinkResult(
            None,
            REGIME_UNAVAILABLE,
            "REGIME OPTIONAL: market-regime evidence was not evaluated.",
        )
        strategy_blocker = _strategy_blocker(
            research.alpha_signals, decision_time=research.decision_time
        )
        result_blockers = tuple(
            dict.fromkeys(item for item in (strategy_blocker, blocker) if item is not None)
        )
        operational_policy_id = research.operational_policy_id
        operational_policy_decision = research.operational_policy_decision
        operationally_allowed = bool(
            research.operational_policy_effective
            and strategy_blocker is None
            and blocker is None
        )
        operational = operationally_allowed
        return TodayResult(
            run_id=0,
            decision_time=research.decision_time,
            market_session="POST_CLOSE_DECISION",
            data_freshness="CERTIFIED_AS_OF_DECISION",
            status="BLOCKED",
            data_certification="APPROVED",
            model_status=(
                (
                    "PROVISIONAL_OPERATIONAL_APPROVED"
                    if operational_policy_id != "NOT_CONFIGURED"
                    else "PRODUCTION_APPROVED"
                )
                if strategy_blocker is None
                else "DIAGNOSTIC_ONLY"
            ),
            portfolio_status="NOT_INITIALIZED",
            risk_regime=link.display_status,
            gross_target=None,
            cash_target=None,
            recommendations=(),
            no_rebalance_reason=None,
            blockers=result_blockers,
            warnings=(),
            data_hash=research.data_version,
            model_hash=research.strategy_version,
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
            model_approval_hash=research.model_approval_hash,
            probability_calibration_status=(
                "CALIBRATED_LOCKED_OOS_PRODUCTION_APPROVED"
                if research.probability_overlay_active
                else "PROBABILITY_NOT_CALIBRATED"
            ),
            risk_regime_detail=link.detail,
            benchmark_evidences=research.benchmark_evidences,
            strategy_version=research.strategy_version,
            production_approval_artifact_id=research.model_approval_hash,
            probability_artifact_id=research.probability_artifact_id,
            universe_snapshot_id=research.universe_snapshot_id,
            universe_evidence=research.universe_evidence,
            probability_overlay_active=research.probability_overlay_active,
            probability_overlay_state=research.probability_overlay_state,
            probability_overlay_reason=research.probability_overlay_reason,
            probability_overlay_effects=research.probability_overlay_effects,
            operational_approval_artifact_id=(
                operational_policy_id
                if operational
                else "NOT_APPROVED"
            ),
            operational_readiness=(
                OperationalReadiness.PROVISIONAL_ACTIONABLE.value
                if operational
                else OperationalReadiness.BLOCKED.value
            ),
            research_certification_state="NOT_CERTIFIABLE",
            operational_policy_id=operational_policy_id,
            operational_policy_decision=operational_policy_decision,
            operational_policy_effective=research.operational_policy_effective,
            operational_policy_reason=research.operational_policy_reason,
            operational_policy_hash=research.operational_policy_hash,
            operational_policy_identity_hash=(
                research.operational_policy_identity_hash
            ),
            signal_authorization_class=research.signal_authorization_class,
            signal_evidence_level=research.signal_evidence_level,
            operationally_allowed=operationally_allowed,
            operational_degraded_reason=_operational_degraded_reason(
                allowed=operational,
                policy_effective=research.operational_policy_effective,
                policy_reason=research.operational_policy_reason,
                blocker=strategy_blocker or blocker,
            ),
        )

    def _operational_policy(self, decision_time: datetime) -> OperationalPolicy | None:
        status = self.operational_store.status(
            resolve_current_operational_identity(
                self.effective_config,
                self.assembler.strategy,
                decision_time=decision_time,
            ),
            research_state="NOT_CERTIFIABLE",
            now=decision_time,
        )
        return status.policy if status.effective else None

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
        classical_output: DailyQuantOutput | None = None,
        regime_link: RegimeLinkResult | None = None,
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
                confidence=(
                    float(item.confidence_score) / 100
                    if item.confidence_score is not None
                    else None
                ),
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
                confidence_source=(
                    "CALIBRATED_LOCKED_OOS"
                    if assembled is not None and assembled.probability_overlay_active
                    else "NOT_CALIBRATED"
                ),
            )
            for item in run.recommendations
        )
        gross = sum(item.target_weight for item in recommendations)
        no_rebalance = None
        if run.status == "no_decision":
            no_rebalance = "all target differences are inside the validated no-trade band"
        data_approved = bool(
            assembled is not None
            and assembled.inputs.authorization.decision.status.value == "APPROVED"
        )
        strategy_blocker = (
            _strategy_blocker(
                assembled.inputs.alpha_signals,
                decision_time=assembled.inputs.decision_time,
            )
            if assembled is not None
            else "STRATEGY_NOT_EVALUATED"
        )
        resolved_data_version = (
            assembled.data_version if assembled is not None else run.data_version
        )
        resolved_strategy_version = (
            assembled.strategy_version if assembled is not None else run.model_version
        )
        lifecycle, lifecycle_blocked_symbols = self._lifecycle_and_blocked(
            run.portfolio_id, run.as_of_time
        )
        if lifecycle_blocked_symbols:
            recommendations = tuple(
                item
                for item in recommendations
                if item.symbol not in set(lifecycle_blocked_symbols)
            )
        return TodayResult(
            run_id=run.id,
            decision_time=run.as_of_time,
            market_session="POST_CLOSE_DECISION",
            data_freshness=(
                "CERTIFIED_AS_OF_DECISION"
                if data_approved
                else "UNAVAILABLE"
            ),
            status=run.status.upper(),
            data_certification="APPROVED" if data_approved else "BLOCKED",
            model_status=(
                (
                    "PROVISIONAL_OPERATIONAL_APPROVED"
                    if assembled is not None
                    and assembled.operational_policy_effective
                    else "PRODUCTION_APPROVED"
                )
                if strategy_blocker is None
                else "DIAGNOSTIC_ONLY"
            ),
            portfolio_status="TARGET_COMPUTED" if run.gate_status == "APPROVED" else "UNCHANGED",
            risk_regime=(
                regime_link.display_status if regime_link is not None else REGIME_UNAVAILABLE
            ),
            gross_target=gross if run.gate_status == "APPROVED" else None,
            cash_target=1 - gross if run.gate_status == "APPROVED" else None,
            recommendations=recommendations,
            no_rebalance_reason=no_rebalance,
            blockers=tuple(run.blockers),
            warnings=(),
            data_hash=resolved_data_version,
            model_hash=resolved_strategy_version,
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
            identity_hashes=self._identity_hashes(resolved_data_version),
            model_approval_hash=(
                assembled.model_approval_hash
                if assembled is not None
                else "NOT_APPROVED"
            ),
            probability_calibration_status=(
                "ACTIVE_CALIBRATED"
                if assembled.probability_overlay_active
                else "FALLBACK_CLASSICAL"
            ) if assembled is not None else "FALLBACK_CLASSICAL",
            stress=output.stress if output is not None else None,
            risk_state=(assembled.inputs.portfolio_risk_state if assembled is not None else None),
            risk_regime_detail=(
                regime_link.detail
                if regime_link is not None
                else "REGIME OPTIONAL: market-regime evidence was not evaluated."
            ),
            benchmark_evidences=(
                assembled.benchmark_evidences if assembled is not None else ()
            ),
            strategy_version=resolved_strategy_version,
            production_approval_artifact_id=(
                assembled.model_approval_hash if assembled is not None else "NOT_APPROVED"
            ),
            portfolio_validation_artifact_id=(
                output.target.model_validation_id
                if output is not None and output.target is not None
                else "NOT_APPROVED"
            ),
            probability_artifact_id=(
                assembled.probability_artifact_id
                if assembled is not None
                else "OPTIONAL_UNAVAILABLE"
            ),
            universe_snapshot_id=(
                assembled.universe_snapshot_id if assembled is not None else "UNAVAILABLE"
            ),
            portfolio_snapshot_id=(
                _portfolio_snapshot_id(assembled)
                if assembled is not None
                else "NOT_INITIALIZED"
            ),
            universe_evidence=(
                assembled.universe_evidence if assembled is not None else {}
            ),
            probability_overlay_active=(
                assembled.probability_overlay_active if assembled is not None else False
            ),
            probability_overlay_state=(
                assembled.probability_overlay_state
                if assembled is not None
                else "RESEARCH_ONLY"
            ),
            probability_overlay_reason=(
                assembled.probability_overlay_reason
                if assembled is not None
                else "PROBABILITY_FALLBACK_CLASSICAL"
            ),
            probability_overlay_effects=(
                assembled.probability_overlay_effects if assembled is not None else ()
            ),
            probability_counterfactual=_probability_counterfactual(
                assembled,
                output,
                classical_output,
            ),
            operational_approval_artifact_id=(
                assembled.operational_policy_id
                if assembled is not None
                and assembled.operational_policy_effective
                and strategy_blocker is None
                and run.status in {"generated", "no_decision"}
                else "NOT_APPROVED"
            ),
            operational_policy_id=(
                assembled.operational_policy_id
                if assembled is not None
                else "NOT_CONFIGURED"
            ),
            operational_policy_decision=(
                assembled.operational_policy_decision
                if assembled is not None
                else OperationalPolicyDecision.BLOCK.value
            ),
            operational_policy_effective=bool(
                assembled is not None and assembled.operational_policy_effective
            ),
            operational_policy_reason=(
                assembled.operational_policy_reason
                if assembled is not None
                else "OPERATIONAL_POLICY_NOT_CONFIGURED"
            ),
            operational_policy_hash=(
                assembled.operational_policy_hash
                if assembled is not None
                else "NOT_CONFIGURED"
            ),
            operational_policy_identity_hash=(
                assembled.operational_policy_identity_hash
                if assembled is not None
                else "NOT_CONFIGURED"
            ),
            signal_authorization_class=(
                assembled.signal_authorization_class
                if assembled is not None
                else "FAIL_BLOCKING"
            ),
            signal_evidence_level=(
                assembled.signal_evidence_level
                if assembled is not None
                else "DIAGNOSTIC_ONLY"
            ),
            operationally_allowed=bool(
                assembled is not None
                and assembled.operational_policy_effective
                and strategy_blocker is None
                and run.status in {"generated", "no_decision"}
            ),
            operational_readiness=(
                OperationalReadiness.PROVISIONAL_ACTIONABLE.value
                if assembled is not None
                and assembled.operational_policy_effective
                and strategy_blocker is None
                and run.status in {"generated", "no_decision"}
                else OperationalReadiness.BLOCKED.value
            ),
            research_certification_state="NOT_CERTIFIABLE",
            operational_degraded_reason=_operational_degraded_reason(
                allowed=bool(
                    assembled is not None
                    and assembled.operational_policy_effective
                    and strategy_blocker is None
                    and run.status in {"generated", "no_decision"}
                ),
                policy_effective=bool(
                    assembled is not None and assembled.operational_policy_effective
                ),
                policy_reason=(
                    assembled.operational_policy_reason
                    if assembled is not None
                    else "OPERATIONAL_POLICY_NOT_CONFIGURED"
                ),
                blocker=strategy_blocker or f"WORKFLOW_STATUS_{run.status.upper()}",
            ),
            lifecycle=lifecycle,
            lifecycle_blocked_symbols=lifecycle_blocked_symbols,
        )

    def _lifecycle_and_blocked(
        self,
        portfolio_id: int,
        decision_time: datetime,
    ) -> tuple[dict[str, object], tuple[str, ...]]:
        """Compute live lifecycle PnL, attribution and corporate-action state.

        Corporate actions are never auto-applied.  Positions with unreconciled
        actions are marked RECONCILIATION_REQUIRED and their symbols are removed
        from today's recommendation list (fail-closed).
        """
        from personal_alpha_terminal.portfolio.lifecycle import (
            PortfolioLifecycleService,
        )

        service = PortfolioLifecycleService(self.session)
        try:
            pnl = service.portfolio_pnl(portfolio_id, as_of=decision_time)
            attribution = service.daily_attribution(portfolio_id, as_of=decision_time)
            reconciliations = service.corporate_action_reconciliation(
                portfolio_id, as_of=decision_time
            )
        except (LookupError, RuntimeError, ValueError) as error:
            return {"status": "UNAVAILABLE", "reason": str(error)}, ()
        blocked = tuple(
            item.symbol
            for item in reconciliations
            if item.status == "RECONCILIATION_REQUIRED"
        )
        lifecycle: dict[str, object] = {
            "status": "OK",
            "pnl": pnl.document(),
            "attribution": attribution.document(),
            "reconciliation": [item.document() for item in reconciliations],
            "blocked_symbols": list(blocked),
        }
        return lifecycle, blocked

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


def _challenger_coefficients(experiment: object) -> dict[str, float]:
    """Extract factor coefficients from a registered challenger experiment.

    Defaults to the classical champion coefficients when the experiment does not
    declare its own, so shadow comparison stays well-defined.
    """
    parameters = getattr(experiment, "parameters", {}) or {}
    return {
        "momentum_coefficient": float(parameters.get("momentum_coefficient", 0.006)),
        "trend_coefficient": float(parameters.get("trend_coefficient", 0.003)),
        "low_volatility_coefficient": float(
            parameters.get("low_volatility_coefficient", 0.002)
        ),
    }


def _strategy_blocker(
    signals: tuple[AlphaSignal, ...], *, decision_time: datetime
) -> str | None:
    approved = tuple(
        item
        for item in signals
        if item.operational_eligible(decision_time)
    )
    if approved:
        return None
    return (
        "STRATEGY_NOT_PRODUCTION_APPROVED: no explicit operational policy or "
        "full production approval is bound to this strategy/config"
    )


def _operational_degraded_reason(
    *,
    allowed: bool,
    policy_effective: bool,
    policy_reason: str,
    blocker: str | None,
) -> str:
    if allowed:
        return (
            "research_certification_state=NOT_CERTIFIABLE; "
            "explicit operational policy allows provisional production advice"
        )
    if not policy_effective:
        return f"{policy_reason}; production advice blocked"
    return blocker or "PRODUCTION_ADVICE_BLOCKED"


def _portfolio_snapshot_id(assembled: AssembledDailyInput) -> str:
    return _fingerprint(
        {
            "cash": assembled.cash_balance,
            "positions": [asdict(item) for item in assembled.portfolio_positions],
            "data_cutoff": assembled.data_cutoff,
        }
    )


def _probability_counterfactual(
    assembled: AssembledDailyInput | None,
    output: DailyQuantOutput | None,
    classical_output: DailyQuantOutput | None,
) -> dict[str, dict[str, object]]:
    if assembled is None or output is None or classical_output is None:
        return {}
    adjusted_signals = {item.symbol: item for item in assembled.inputs.alpha_signals}
    classical_signals = {item.symbol: item for item in assembled.classical_alpha_signals}
    effects = {item.symbol: item for item in assembled.probability_overlay_effects}
    with_targets = output.target.target_weights if output.target is not None else {}
    without_targets = (
        classical_output.target.target_weights
        if classical_output.target is not None
        else {}
    )
    with_actions = _trace_actions(output)
    without_actions = _trace_actions(classical_output)
    symbols = sorted(
        set(adjusted_signals)
        | set(classical_signals)
        | set(with_targets)
        | set(without_targets)
        | set(assembled.inputs.current_weights)
    )
    traces: dict[str, dict[str, object]] = {}
    for symbol in symbols:
        base = classical_signals.get(symbol)
        adjusted = adjusted_signals.get(symbol)
        effect = effects.get(symbol)
        target_without = float(without_targets.get(symbol, 0.0))
        target_with = float(with_targets.get(symbol, 0.0))
        decision_without = without_actions.get(symbol, "NO_ACTION")
        final_decision = with_actions.get(symbol, "NO_ACTION")
        traces[symbol] = {
            "ticker": symbol,
            "base_alpha": (
                float(base.expected_excess_return) if base is not None else None
            ),
            "conditional_probability": (
                float(effect.posterior_probability) if effect is not None else None
            ),
            "probability_reliability": (
                f"CALIBRATED_LOCKED_OOS:n={effect.sample_size}"
                if effect is not None
                else "UNAVAILABLE_FALLBACK"
            ),
            "probability_adjusted_alpha": (
                float(adjusted.expected_excess_return)
                if adjusted is not None
                else None
            ),
            "target_without_probability": target_without,
            "target_with_probability": target_with,
            "pre_risk_target": "NOT_EXPOSED_BY_ENGINE",
            "post_risk_target": "NOT_EXPOSED_BY_ENGINE",
            "final_target": target_with,
            "probability_weight_impact": target_with - target_without,
            "decision_without_probability": decision_without,
            "final_decision": final_decision,
            "decision_changed_without_probability": decision_without != final_decision,
        }
    return traces


def _trace_actions(output: DailyQuantOutput) -> dict[str, str]:
    labels = {
        TradeAction.INCREASE: "ADD",
        TradeAction.SELL: "EXIT",
    }
    return {
        item.ticker: labels.get(item.action, item.action.value)
        for item in output.trades
    }


def _fingerprint(payload: dict[str, object]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
