from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from math import floor

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.data.us_market.session import CertifiedUSSessionService
from personal_alpha_terminal.models import (
    Price,
    QuantDecisionRecommendation,
    QuantDecisionRun,
    SecurityMaster,
)
from personal_alpha_terminal.quant_engine.input_assembler import (
    ProductionDailyQuantInputAssembler,
)
from personal_alpha_terminal.quant_engine.portfolio.trades import TradeAction
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantPipeline,
    ProductionPipelineStatus,
)


@dataclass(frozen=True, slots=True)
class TodayRecommendation:
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


class ProductionDailyWorkflow:
    """Headless production daily path; failures persist diagnosis, never actions."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.assembler = ProductionDailyQuantInputAssembler(session)
        self.pipeline = DailyQuantPipeline()
        self.sessions = CertifiedUSSessionService(session)

    def run(self, *, portfolio_id: int, decision_time: datetime) -> TodayResult:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        try:
            assembled = self.assembler.assemble(
                portfolio_id=portfolio_id,
                decision_time=decision_time,
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
            return self._result_from_record(existing, assembled.parameter_fingerprint)

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
            return self._result_from_record(run, assembled.parameter_fingerprint)

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
        return self._result_from_record(run, assembled.parameter_fingerprint)

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
    ) -> TodayResult:
        recommendations = tuple(
            TodayRecommendation(
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
            config_hash=config_hash,
        )


def _fingerprint(payload: dict[str, object]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
