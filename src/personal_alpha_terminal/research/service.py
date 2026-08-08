from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.core.market_time import normalize_utc
from personal_alpha_terminal.models import (
    MarketDataQualityRun,
    MarketUniverseSnapshot,
    ResearchDataCertification,
)
from personal_alpha_terminal.research.data_gate import (
    GateDecision,
    ResearchDataAuthorization,
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
)


class ResearchDataGateService:
    """Build gate evidence from persisted certification records, never row-count inference."""

    def __init__(self, session: Session, gate: ResearchDataGate | None = None) -> None:
        self._session = session
        self._gate = gate or ResearchDataGate()

    def evaluate(self, request: ResearchDataRequest) -> GateDecision:
        return self._gate.evaluate(request, self.evidence(request))

    def authorize(self, request: ResearchDataRequest) -> ResearchDataAuthorization:
        return self._gate.authorize(request, self.evidence(request))

    def evidence(self, request: ResearchDataRequest) -> ResearchDataEvidence:
        certification = self._session.scalar(
            select(ResearchDataCertification)
            .where(
                ResearchDataCertification.market == request.market,
                ResearchDataCertification.asset_type == request.asset_type,
                ResearchDataCertification.valid_from <= request.decision_time,
                (
                    ResearchDataCertification.valid_until.is_(None)
                    | (ResearchDataCertification.valid_until >= request.decision_time)
                ),
            )
            .order_by(
                ResearchDataCertification.created_at.desc(),
                ResearchDataCertification.id.desc(),
            )
            .limit(1)
        )
        quality_statement = select(MarketDataQualityRun)
        if certification is not None:
            quality_statement = quality_statement.where(
                MarketDataQualityRun.id == certification.quality_run_id
            )
        quality = self._session.scalar(
            quality_statement.order_by(
                MarketDataQualityRun.created_at.desc(), MarketDataQualityRun.id.desc()
            ).limit(1)
        )
        metrics = quality.aggregate_metrics if quality is not None else {}
        snapshot = self._session.scalar(
            select(MarketUniverseSnapshot)
            .where(
                MarketUniverseSnapshot.market == request.market,
                MarketUniverseSnapshot.as_of_date <= request.end_date,
                MarketUniverseSnapshot.available_time <= request.decision_time,
            )
            .order_by(
                MarketUniverseSnapshot.as_of_date.desc(),
                MarketUniverseSnapshot.id.desc(),
            )
            .limit(1)
        )
        source_ids: list[str] = []
        if quality is not None:
            source_ids.append(f"quality-run:{quality.id}")
            source_ids.extend(f"universe-snapshot:{item}" for item in quality.source_snapshot_ids)
        if snapshot is not None:
            source_ids.append(f"universe-snapshot:{snapshot.id}")

        missing_rate = self._rate(metrics.get("missing_rate"))
        anomaly_rate = self._rate(metrics.get("anomaly_rate"))
        if quality is not None and quality.results:
            missing_rate = max(float(item.missing_rate) for item in quality.results)
            anomaly_rate = max(float(item.anomaly_rate) for item in quality.results)

        available = self._datetime(metrics.get("latest_available_time"))
        if available is None and quality is not None:
            available = normalize_utc(quality.updated_at)
        expected_snapshot = str(snapshot.id) if snapshot is not None else None
        if certification is not None and certification.universe_snapshot_id is not None:
            expected_snapshot = str(certification.universe_snapshot_id)
        return ResearchDataEvidence(
            market=request.market,
            asset_type=request.asset_type,
            quality_status=quality.status if quality is not None else "missing",
            source=(snapshot.source if snapshot is not None else str(metrics.get("source", ""))),
            provider=(
                snapshot.provider if snapshot is not None else str(metrics.get("provider", ""))
            ),
            source_ids=tuple(dict.fromkeys(source_ids)),
            latest_available_time=available,
            point_in_time_status=str(metrics.get("us_point_in_time_status", "missing")),
            adjustment_mode=str(metrics.get("us_adjustment_mode", "unknown")),
            universe_snapshot_id=expected_snapshot,
            universe_available_time=(
                normalize_utc(snapshot.available_time) if snapshot is not None else None
            ),
            corporate_actions_complete=(metrics.get("us_corporate_actions_certified") is True),
            trading_calendar_complete=(metrics.get("us_trading_calendar_certified") is True),
            missing_rate=missing_rate,
            anomaly_rate=anomaly_rate,
            maximum_missing_rate=self._rate(metrics.get("maximum_missing_rate")) or 0.01,
            maximum_anomaly_rate=self._rate(metrics.get("maximum_anomaly_rate")) or 0.005,
            data_version=(
                certification.data_version
                if certification is not None
                else str(metrics.get("data_version", ""))
            ),
            allow_backtest=(
                certification.status == "APPROVED" and certification.allow_backtest
                if certification is not None
                else metrics.get("allow_backtest") is True
            ),
            allow_display=(
                certification.allow_display
                if certification is not None
                else metrics.get("allow_display") is True
            ),
            allow_portfolio_decision=(
                certification.status == "APPROVED"
                and certification.allow_portfolio_decision
                if certification is not None
                else metrics.get("allow_portfolio_decision") is True
            ),
            dual_source_verified=metrics.get("us_dual_source_verified") is True,
            source_conflict=bool(metrics.get("source_conflict", False)),
            fundamentals_vintage_complete=(metrics.get("us_pit_fundamentals_certified") is True),
            earnings_vintage_complete=(metrics.get("us_pit_earnings_certified") is True),
        )

    @staticmethod
    def _rate(value: object) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float, str)):
            return float(value)
        return None

    @staticmethod
    def _datetime(value: object) -> datetime | None:
        if isinstance(value, datetime):
            return normalize_utc(value)
        if isinstance(value, str) and value.strip():
            return normalize_utc(datetime.fromisoformat(value))
        return cast(datetime | None, None)
