from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from personal_alpha_terminal.data.market_data_quality.schemas import AdjustmentMode
from personal_alpha_terminal.models import (
    CorporateAction,
    ExchangeSession,
    Financial,
    MarketDataQualityRun,
    MarketUniverseSnapshot,
    Price,
    Stock,
)
from personal_alpha_terminal.research import (
    GateDecision,
    ResearchDataGateService,
    ResearchDataRequest,
    ResearchPurpose,
)
from personal_alpha_terminal.strategies.us_adaptive_alpha.data_gate import (
    assess_sleeves,
    evaluate_data_gate,
)
from personal_alpha_terminal.strategies.us_adaptive_alpha.schemas import (
    DataGateDecision,
    DataGateInput,
    ResearchCapabilities,
    SleeveAssessment,
)


@dataclass(frozen=True, slots=True)
class USAdaptiveAlphaOverview:
    generated_at: datetime
    data_gate: DataGateDecision
    capabilities: ResearchCapabilities
    sleeves: tuple[SleeveAssessment, ...]
    source_ids: tuple[str, ...]
    production_gate: GateDecision


class USAdaptiveAlphaService:
    """Read-only production-capability view for the research framework."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def overview(self) -> USAdaptiveAlphaOverview:
        latest_quality = self._session.scalar(
            select(MarketDataQualityRun)
            .order_by(MarketDataQualityRun.created_at.desc(), MarketDataQualityRun.id.desc())
            .limit(1)
        )
        quality_status = latest_quality.status if latest_quality is not None else "missing"
        sample_count = latest_quality.sample_count if latest_quality is not None else 0
        source_ids = (
            tuple(f"quality:{item}" for item in latest_quality.source_snapshot_ids)
            if latest_quality is not None
            else ()
        )
        certification = (
            latest_quality.aggregate_metrics if latest_quality is not None else {}
        )
        security_count = self._count(
            select(func.count(Stock.id)).where(Stock.market == "US")
        )
        universe_count = self._count(
            select(func.count(MarketUniverseSnapshot.id)).where(
                MarketUniverseSnapshot.market == "US"
            )
        )
        calendar_count = self._count(
            select(func.count(ExchangeSession.id)).where(
                ExchangeSession.exchange.in_(("XNYS", "XNAS", "NYSE", "NASDAQ"))
            )
        )
        action_count = self._count(
            select(func.count(CorporateAction.id))
            .join(Stock, Stock.id == CorporateAction.stock_id)
            .where(Stock.market == "US")
        )
        pit_price_count = self._count(
            select(func.count(Price.id))
            .join(Stock, Stock.id == Price.stock_id)
            .where(
                Stock.market == "US",
                Price.adjustment_method == AdjustmentMode.POINT_IN_TIME_TOTAL_RETURN.value,
            )
        )
        pit_financial_count = self._count(
            select(func.count(Financial.id))
            .join(Stock, Stock.id == Financial.stock_id)
            .where(
                Stock.market == "US",
                Financial.available_at.is_not(None),
                Financial.source != "legacy_unknown",
            )
        )
        inputs = DataGateInput(
            market="US",
            quality_status=quality_status,
            sample_count=sample_count,
            security_master_ready=(
                security_count >= 100
                and certification.get("us_security_master_certified") is True
            ),
            point_in_time_universe_ready=(
                universe_count >= 2
                and certification.get("us_pit_universe_certified") is True
            ),
            trading_calendar_ready=(
                calendar_count >= 252
                and certification.get("us_trading_calendar_certified") is True
            ),
            corporate_actions_ready=(
                action_count > 0
                and certification.get("us_corporate_actions_certified") is True
            ),
            point_in_time_total_return_ready=(
                pit_price_count > 0
                and certification.get("us_pit_total_return_certified") is True
            ),
            source_conflict=bool(
                latest_quality
                and any("conflict" in item.lower() for item in latest_quality.blockers)
            ),
            stale=latest_quality is None,
            as_of_time=latest_quality.updated_at if latest_quality is not None else None,
            source_ids=source_ids,
        )
        gate = evaluate_data_gate(inputs)
        today = datetime.now(UTC)
        production_gate = ResearchDataGateService(self._session).evaluate(
            ResearchDataRequest(
                purpose=ResearchPurpose.PORTFOLIO_DECISION,
                market="US",
                asset_type="stock",
                start_date=date(2010, 1, 1),
                end_date=today.date(),
                decision_time=today,
                adjustment_mode=AdjustmentMode.POINT_IN_TIME_TOTAL_RETURN.value,
                universe_snapshot_id=(
                    str(certification.get("us_active_universe_snapshot_id"))
                    if certification.get("us_active_universe_snapshot_id") is not None
                    else None
                ),
            )
        )
        capabilities = ResearchCapabilities(
            pit_prices=(
                pit_price_count > 0
                and certification.get("us_pit_total_return_certified") is True
            ),
            pit_fundamentals=(
                pit_financial_count > 0
                and certification.get("us_pit_fundamentals_certified") is True
            ),
            pit_sector_membership=(
                universe_count >= 2
                and certification.get("us_pit_sector_membership_certified") is True
            ),
            pit_earnings_events=False,
            benchmark_history=(
                certification.get("us_benchmark_history_certified") is True
            ),
            calibrated_regime=(
                certification.get("us_regime_calibration_certified") is True
            ),
            corrected_relationships=(
                certification.get("us_relationship_oos_certified") is True
            ),
            conditional_oos_history=(
                certification.get("us_conditional_oos_certified") is True
            ),
            defensive_asset_history=(
                certification.get("us_defensive_assets_certified") is True
            ),
        )
        return USAdaptiveAlphaOverview(
            generated_at=datetime.now(UTC),
            data_gate=gate,
            capabilities=capabilities,
            sleeves=assess_sleeves(gate, capabilities),
            source_ids=source_ids,
            production_gate=production_gate,
        )

    def _count(self, statement: Select[tuple[int]]) -> int:
        return int(self._session.scalar(statement) or 0)
