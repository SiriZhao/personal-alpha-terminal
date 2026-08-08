from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from hashlib import sha256


class GateStatus(StrEnum):
    APPROVED = "APPROVED"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


class ResearchPurpose(StrEnum):
    DISPLAY = "display"
    RESEARCH = "research"
    BACKTEST = "backtest"
    PORTFOLIO_DECISION = "portfolio_decision"
    REBALANCE = "rebalance"
    REPORT = "report"


_DECISION_PURPOSES = {
    ResearchPurpose.PORTFOLIO_DECISION,
    ResearchPurpose.REBALANCE,
}
_PIT_PURPOSES = {
    ResearchPurpose.BACKTEST,
    ResearchPurpose.PORTFOLIO_DECISION,
    ResearchPurpose.REBALANCE,
}


@dataclass(frozen=True, slots=True)
class ResearchDataRequest:
    purpose: ResearchPurpose
    market: str
    asset_type: str
    start_date: date
    end_date: date
    decision_time: datetime
    adjustment_mode: str
    universe_snapshot_id: str | None = None
    maximum_age: timedelta = timedelta(days=3)

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError("research data start_date cannot follow end_date")
        if self.decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        if self.maximum_age < timedelta(0):
            raise ValueError("maximum_age cannot be negative")


@dataclass(frozen=True, slots=True)
class ResearchDataEvidence:
    market: str
    asset_type: str
    quality_status: str
    source: str
    provider: str
    source_ids: tuple[str, ...]
    latest_available_time: datetime | None
    point_in_time_status: str
    adjustment_mode: str
    universe_snapshot_id: str | None
    universe_available_time: datetime | None
    corporate_actions_complete: bool
    trading_calendar_complete: bool
    missing_rate: float | None
    anomaly_rate: float | None
    maximum_missing_rate: float
    maximum_anomaly_rate: float
    data_version: str
    allow_backtest: bool
    allow_display: bool
    allow_portfolio_decision: bool
    dual_source_verified: bool
    source_conflict: bool = False
    fundamentals_vintage_complete: bool = False
    earnings_vintage_complete: bool = False

    def __post_init__(self) -> None:
        for name in ("latest_available_time", "universe_available_time"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        for name in (
            "missing_rate",
            "anomaly_rate",
            "maximum_missing_rate",
            "maximum_anomaly_rate",
        ):
            value = getattr(self, name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class GateDecision:
    status: GateStatus
    purpose: ResearchPurpose
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    evidence_fingerprint: str
    evaluated_at: datetime

    @property
    def may_rank_securities(self) -> bool:
        return self.status is GateStatus.APPROVED and self.purpose in {
            ResearchPurpose.RESEARCH,
            ResearchPurpose.PORTFOLIO_DECISION,
            ResearchPurpose.REBALANCE,
        }

    @property
    def may_generate_positions(self) -> bool:
        return self.status is GateStatus.APPROVED and self.purpose in _DECISION_PURPOSES


@dataclass(frozen=True, slots=True)
class ResearchDataAuthorization:
    decision: GateDecision
    request: ResearchDataRequest
    issued_at: datetime
    authorization_id: str
    evidence: ResearchDataEvidence | None = None

    def permits(self, purpose: ResearchPurpose) -> bool:
        if self.request.purpose is not purpose or self.decision.status is GateStatus.BLOCKED:
            return False
        if purpose in _PIT_PURPOSES:
            return self.decision.status is GateStatus.APPROVED
        return True


class ResearchDataBlockedError(RuntimeError):
    def __init__(self, decision: GateDecision) -> None:
        details = "; ".join(decision.blockers) or "research data was not approved"
        super().__init__(f"ResearchDataGate {decision.status.value}: {details}")
        self.decision = decision


class ResearchDataGate:
    """Single fail-closed authorization point for every production research workflow."""

    def evaluate(
        self,
        request: ResearchDataRequest,
        evidence: ResearchDataEvidence,
        *,
        evaluated_at: datetime | None = None,
    ) -> GateDecision:
        now = (evaluated_at or datetime.now(UTC)).astimezone(UTC)
        blockers: list[str] = []
        warnings: list[str] = []

        if request.market != evidence.market:
            blockers.append("requested market does not match certified evidence")
        if request.asset_type != evidence.asset_type:
            blockers.append("requested asset type does not match certified evidence")
        if request.market != "US" and request.purpose in _DECISION_PURPOSES:
            blockers.append("production portfolio decisions are currently limited to US data")
        if evidence.quality_status.lower() != "passed":
            blockers.append(f"data quality status is {evidence.quality_status!r}")
        if evidence.source_conflict:
            blockers.append("unresolved provider disagreement exists")
        if not evidence.source.strip() or not evidence.provider.strip() or not evidence.source_ids:
            blockers.append("complete provider lineage is required")
        if not evidence.data_version.strip():
            blockers.append("immutable data version is missing")
        if evidence.latest_available_time is None:
            blockers.append("latest data availability time is missing")
        elif evidence.latest_available_time.astimezone(UTC) > request.decision_time.astimezone(UTC):
            blockers.append("data became available after the decision cutoff")
        elif now - evidence.latest_available_time.astimezone(UTC) > request.maximum_age:
            if request.purpose in _DECISION_PURPOSES:
                blockers.append("data is stale for a portfolio decision")
            else:
                warnings.append("data is stale for the requested research use")

        if evidence.missing_rate is None or evidence.anomaly_rate is None:
            blockers.append("quality rates require non-zero verified denominators")
        else:
            if evidence.missing_rate > evidence.maximum_missing_rate:
                blockers.append("missing-data rate exceeds the certified threshold")
            if evidence.anomaly_rate > evidence.maximum_anomaly_rate:
                blockers.append("anomaly rate exceeds the certified threshold")

        if not evidence.allow_display and request.purpose is ResearchPurpose.DISPLAY:
            blockers.append("dataset is not approved even for display")
        if request.purpose is ResearchPurpose.BACKTEST and not evidence.allow_backtest:
            blockers.append("dataset is not approved for backtesting")
        if request.purpose in _DECISION_PURPOSES and not evidence.allow_portfolio_decision:
            blockers.append("dataset is not approved for portfolio decisions")

        if request.purpose in _PIT_PURPOSES:
            if evidence.point_in_time_status != "certified":
                blockers.append("point-in-time status is not certified")
            if request.adjustment_mode != "point_in_time_total_return":
                blockers.append("PIT workflows require point_in_time_total_return")
            if evidence.adjustment_mode != request.adjustment_mode:
                blockers.append("requested adjustment mode does not match the evidence")
            if not request.universe_snapshot_id:
                blockers.append("historical universe snapshot is mandatory")
            elif request.universe_snapshot_id != evidence.universe_snapshot_id:
                blockers.append("universe snapshot does not match the certified evidence")
            if evidence.universe_available_time is None:
                blockers.append("universe availability time is missing")
            elif evidence.universe_available_time.astimezone(
                UTC
            ) > request.decision_time.astimezone(UTC):
                blockers.append("universe snapshot was not available at the decision cutoff")
            if not evidence.corporate_actions_complete:
                blockers.append("corporate-action ledger is incomplete")
            if not evidence.trading_calendar_complete:
                blockers.append("exchange calendar is incomplete")

        if request.purpose in _DECISION_PURPOSES and not evidence.dual_source_verified:
            blockers.append("portfolio decisions require second-source verification")
        elif not evidence.dual_source_verified:
            warnings.append("second-source verification is incomplete")

        if blockers:
            status = GateStatus.BLOCKED
        elif request.purpose in _DECISION_PURPOSES | {ResearchPurpose.BACKTEST}:
            status = GateStatus.APPROVED
        elif warnings:
            status = (
                GateStatus.DEGRADED
                if request.purpose is ResearchPurpose.DISPLAY
                else GateStatus.RESEARCH_ONLY
            )
        elif request.purpose in {ResearchPurpose.RESEARCH, ResearchPurpose.REPORT}:
            status = GateStatus.RESEARCH_ONLY
        else:
            status = GateStatus.APPROVED

        actions = self._allowed_actions(status, request.purpose)
        fingerprint = self._fingerprint(request, evidence)
        return GateDecision(
            status=status,
            purpose=request.purpose,
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
            allowed_actions=actions,
            evidence_fingerprint=fingerprint,
            evaluated_at=now,
        )

    def authorize(
        self,
        request: ResearchDataRequest,
        evidence: ResearchDataEvidence,
        *,
        evaluated_at: datetime | None = None,
    ) -> ResearchDataAuthorization:
        decision = self.evaluate(request, evidence, evaluated_at=evaluated_at)
        if decision.status is GateStatus.BLOCKED:
            raise ResearchDataBlockedError(decision)
        if request.purpose in _PIT_PURPOSES and decision.status is not GateStatus.APPROVED:
            raise ResearchDataBlockedError(decision)
        issued_at = decision.evaluated_at
        authorization_id = sha256(
            f"{decision.evidence_fingerprint}|{request.purpose}|{issued_at.isoformat()}".encode()
        ).hexdigest()
        return ResearchDataAuthorization(
            decision,
            request,
            issued_at,
            authorization_id,
            evidence,
        )

    @staticmethod
    def require(
        authorization: ResearchDataAuthorization,
        purpose: ResearchPurpose,
    ) -> None:
        if not authorization.permits(purpose):
            raise ResearchDataBlockedError(authorization.decision)

    @staticmethod
    def _allowed_actions(
        status: GateStatus,
        purpose: ResearchPurpose,
    ) -> tuple[str, ...]:
        if status is GateStatus.BLOCKED:
            return ("diagnostics", "data_validation")
        if status is GateStatus.DEGRADED:
            return ("display", "diagnostics")
        if status is GateStatus.RESEARCH_ONLY:
            return ("descriptive_research", "report_with_limitations")
        if purpose is ResearchPurpose.BACKTEST:
            return ("backtest", "reproducible_report")
        if purpose in _DECISION_PURPOSES:
            return ("ranking", "target_weights", "manual_rebalance_ticket")
        return ("display", "research")

    @staticmethod
    def _fingerprint(
        request: ResearchDataRequest,
        evidence: ResearchDataEvidence,
    ) -> str:
        payload = {
            "request": asdict(request),
            "evidence": asdict(evidence),
        }
        encoded = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
        return sha256(encoded.encode()).hexdigest()
