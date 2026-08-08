from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from json import dumps
from math import floor

from personal_alpha_terminal.decision_engine.schemas import (
    DecisionAction,
    DecisionBatch,
    DecisionBatchStatus,
    DecisionCandidate,
    DecisionRecommendation,
)
from personal_alpha_terminal.research import (
    ResearchDataAuthorization,
    ResearchPurpose,
)


@dataclass(frozen=True, slots=True)
class DecisionEngineConfig:
    model_version: str = "validated-alpha-decision-v2"
    minimum_probability_sample: int = 30
    minimum_confidence_score: float = 60.0
    maximum_data_age: timedelta = timedelta(days=3)
    minimum_weight_change: float = 0.01
    risk_veto_score: float = 80.0
    recommendation_lifetime: timedelta = timedelta(days=3)


class DecisionEngine:
    """Explainable action synthesis. AI output is intentionally not an input."""

    def __init__(self, config: DecisionEngineConfig | None = None) -> None:
        self.config = config or DecisionEngineConfig()

    def generate(
        self,
        *,
        authorization: ResearchDataAuthorization,
        portfolio_id: int,
        portfolio_value: float,
        candidates: tuple[DecisionCandidate, ...],
        generated_at: datetime,
        earliest_execution_time: datetime,
    ) -> DecisionBatch:
        if portfolio_id <= 0 or portfolio_value <= 0:
            raise ValueError("decision generation requires a positive portfolio and value")
        if generated_at.tzinfo is None or earliest_execution_time.tzinfo is None:
            raise ValueError("decision timestamps must be timezone-aware")
        if earliest_execution_time <= generated_at:
            raise ValueError("execution must occur after decision generation")
        source_ids = tuple(sorted({source for item in candidates for source in item.source_ids}))
        fingerprint = _input_fingerprint(
            portfolio_id=portfolio_id,
            candidates=candidates,
            generated_at=generated_at,
            model_version=self.config.model_version,
        )
        if not authorization.permits(ResearchPurpose.PORTFOLIO_DECISION):
            return DecisionBatch(
                portfolio_id=portfolio_id,
                as_of_time=generated_at,
                status=DecisionBatchStatus.BLOCKED,
                gate_status=authorization.decision.status.value,
                authorization_id=authorization.authorization_id,
                data_version=authorization.decision.evidence_fingerprint,
                model_version=self.config.model_version,
                input_fingerprint=fingerprint,
                source_ids=source_ids,
                blockers=authorization.decision.blockers or ("ResearchDataGate not approved",),
                recommendations=(),
            )
        if not candidates:
            return self._no_decision(
                authorization,
                portfolio_id,
                generated_at,
                fingerprint,
                source_ids,
                ("No complete quantitative candidate evidence was supplied.",),
            )
        recommendations: list[DecisionRecommendation] = []
        blockers: list[str] = []
        seen: set[int] = set()
        for candidate in sorted(candidates, key=lambda item: item.permanent_security_id):
            if candidate.stock_id in seen:
                raise ValueError("decision candidates contain duplicate permanent assets")
            seen.add(candidate.stock_id)
            candidate_blockers = self._candidate_blockers(candidate, generated_at)
            if candidate_blockers:
                blockers.extend(
                    f"{candidate.ticker}: {message}" for message in candidate_blockers
                )
                continue
            recommendation = self._recommendation(
                candidate,
                portfolio_value=portfolio_value,
                generated_at=generated_at,
                earliest_execution_time=earliest_execution_time,
                data_version=authorization.decision.evidence_fingerprint,
            )
            if recommendation is None:
                blockers.append(
                    f"{candidate.ticker}: evidence confidence below decision threshold"
                )
            else:
                recommendations.append(recommendation)
        if not recommendations:
            return self._no_decision(
                authorization,
                portfolio_id,
                generated_at,
                fingerprint,
                source_ids,
                tuple(blockers) or ("No candidate passed the decision evidence threshold.",),
            )
        return DecisionBatch(
            portfolio_id=portfolio_id,
            as_of_time=generated_at,
            status=DecisionBatchStatus.GENERATED,
            gate_status=authorization.decision.status.value,
            authorization_id=authorization.authorization_id,
            data_version=authorization.decision.evidence_fingerprint,
            model_version=self.config.model_version,
            input_fingerprint=fingerprint,
            source_ids=source_ids,
            blockers=tuple(blockers),
            recommendations=tuple(recommendations),
        )

    def _candidate_blockers(
        self,
        candidate: DecisionCandidate,
        generated_at: datetime,
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        age = generated_at - candidate.as_of_time
        if age < timedelta(0):
            blockers.append("evidence is timestamped after the decision time")
        elif age > self.config.maximum_data_age:
            blockers.append("evidence is stale")
        if candidate.probability_sample_size < self.config.minimum_probability_sample:
            blockers.append("conditional evidence sample is below the minimum")
        if not candidate.probability_calibrated:
            blockers.append("conditional evidence is not calibrated")
        if not candidate.oos_validated:
            blockers.append("candidate has no locked out-of-sample validation")
        if candidate.alpha_validation_status != "PRODUCTION_APPROVED":
            blockers.append("alpha model is not PRODUCTION_APPROVED")
        if candidate.expected_excess_return is None:
            blockers.append("validated expected excess return is missing")
        if not candidate.alpha_pit_valid:
            blockers.append("alpha input is not point-in-time valid")
        if candidate.portfolio_validation_status != "PRODUCTION_APPROVED":
            blockers.append("portfolio construction is not PRODUCTION_APPROVED")
        if not candidate.risk_constraints_applied:
            blockers.append("portfolio risk constraints were not applied")
        return tuple(blockers)

    def _recommendation(
        self,
        candidate: DecisionCandidate,
        *,
        portfolio_value: float,
        generated_at: datetime,
        earliest_execution_time: datetime,
        data_version: str,
    ) -> DecisionRecommendation | None:
        assert candidate.expected_excess_return is not None
        component_scores = _component_scores(candidate)
        # Retained for the existing presentation/storage contract only. It is
        # validation confidence, not a magic action score.
        quant_score = candidate.alpha_confidence * 100
        confidence = candidate.alpha_confidence * 100
        if confidence < self.config.minimum_confidence_score:
            return None
        delta = candidate.optimized_target_weight - candidate.current_weight
        risk_veto = candidate.risk_score >= self.config.risk_veto_score and delta > 0
        if risk_veto:
            action = DecisionAction.WATCH
            target_weight = candidate.current_weight
            suggested_shares = 0
        elif delta >= self.config.minimum_weight_change:
            action = DecisionAction.BUY
            target_weight = candidate.optimized_target_weight
            suggested_shares = _shares(
                delta,
                portfolio_value,
                candidate.reference_price,
                candidate.lot_size,
                candidate.maximum_shares,
            )
        elif delta <= -self.config.minimum_weight_change:
            action = DecisionAction.SELL
            target_weight = candidate.optimized_target_weight
            suggested_shares = _shares(
                delta,
                portfolio_value,
                candidate.reference_price,
                candidate.lot_size,
                candidate.maximum_shares,
            )
        else:
            action = DecisionAction.HOLD
            target_weight = candidate.current_weight
            suggested_shares = 0
        rationale = (
            *candidate.rationale,
            f"expected_excess_return={candidate.expected_excess_return:.6f}",
            f"alpha_validation={candidate.alpha_validation_status}",
            f"alpha_model={candidate.alpha_model_version}",
            f"alpha_data={candidate.alpha_data_version}",
            f"portfolio_model={candidate.portfolio_model_version}",
            f"optimizer_target={candidate.optimized_target_weight:.2%}",
        )
        if risk_veto:
            rationale = (*rationale, "risk veto blocked an increase; manual observation only")
        recommendation_id = sha256(
            (
                f"{candidate.permanent_security_id}|{generated_at.isoformat()}|"
                f"{data_version}|{self.config.model_version}"
            ).encode()
        ).hexdigest()[:48]
        return DecisionRecommendation(
            recommendation_id=f"QD-{recommendation_id}",
            stock_id=candidate.stock_id,
            ticker=candidate.ticker,
            permanent_security_id=candidate.permanent_security_id,
            action=action,
            current_weight=candidate.current_weight,
            target_weight=target_weight,
            quant_score=quant_score,
            confidence_score=confidence,
            component_scores=component_scores,
            rationale=rationale,
            risk_factors=candidate.risk_factors,
            evidence_grade="PRODUCTION_APPROVED",
            sample_size=candidate.probability_sample_size,
            source_ids=candidate.source_ids,
            reference_price=candidate.reference_price,
            suggested_shares=suggested_shares,
            earliest_execution_time=earliest_execution_time,
            expires_at=generated_at + self.config.recommendation_lifetime,
        )

    def _no_decision(
        self,
        authorization: ResearchDataAuthorization,
        portfolio_id: int,
        generated_at: datetime,
        fingerprint: str,
        source_ids: tuple[str, ...],
        blockers: tuple[str, ...],
    ) -> DecisionBatch:
        return DecisionBatch(
            portfolio_id=portfolio_id,
            as_of_time=generated_at,
            status=DecisionBatchStatus.NO_DECISION,
            gate_status=authorization.decision.status.value,
            authorization_id=authorization.authorization_id,
            data_version=authorization.decision.evidence_fingerprint,
            model_version=self.config.model_version,
            input_fingerprint=fingerprint,
            source_ids=source_ids,
            blockers=blockers,
            recommendations=(),
        )


def _component_scores(candidate: DecisionCandidate) -> dict[str, float]:
    return {
        "expected_excess_return": float(candidate.expected_excess_return or 0.0),
        "alpha_confidence": candidate.alpha_confidence,
        "risk_score": candidate.risk_score,
        "portfolio_target_delta": (
            candidate.optimized_target_weight - candidate.current_weight
        ),
    }


def _shares(
    delta_weight: float,
    portfolio_value: float,
    price: float,
    lot_size: int,
    maximum_shares: int,
) -> int:
    raw = delta_weight * portfolio_value / price
    sign = 1 if raw > 0 else -1
    rounded = sign * floor(abs(raw) / lot_size) * lot_size
    return max(-maximum_shares, min(maximum_shares, rounded))


def _input_fingerprint(
    *,
    portfolio_id: int,
    candidates: tuple[DecisionCandidate, ...],
    generated_at: datetime,
    model_version: str,
) -> str:
    return sha256(
        dumps(
            {
                "portfolio_id": portfolio_id,
                "generated_at": generated_at.isoformat(),
                "model_version": model_version,
                "candidates": [
                    {
                        **asdict(item),
                        "as_of_time": item.as_of_time.isoformat(),
                    }
                    for item in candidates
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
