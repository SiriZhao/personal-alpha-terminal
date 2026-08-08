from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from personal_alpha_terminal.intelligence.scanner import (
    CandidateStatus,
    DailyOpportunityScanner,
    ScannerMode,
)
from personal_alpha_terminal.intelligence.storage import (
    DatabaseExtractionCache,
    IntelligenceRepository,
)
from personal_alpha_terminal.models.base import Base
from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.portfolio.trades import (
    TradeAction,
    TradeProposal,
)
from personal_alpha_terminal.research.data_gate import (
    GateDecision,
    GateStatus,
    ResearchDataAuthorization,
    ResearchDataRequest,
    ResearchPurpose,
)
from tests.unit.intelligence.helpers import make_event

NOW = datetime(2026, 8, 8, 12, tzinfo=UTC)


def _authorization(purpose: ResearchPurpose, status: GateStatus) -> ResearchDataAuthorization:
    request = ResearchDataRequest(
        purpose=purpose,
        market="US",
        asset_type="stock",
        start_date=date(2020, 1, 1),
        end_date=date(2026, 8, 7),
        decision_time=NOW,
        adjustment_mode="point_in_time_total_return",
        universe_snapshot_id="universe-v1",
    )
    decision = GateDecision(
        status,
        purpose,
        () if status is not GateStatus.BLOCKED else ("quality failed",),
        (),
        ("ranking",),
        "fingerprint",
        NOW,
    )
    return ResearchDataAuthorization(decision, request, NOW, "auth-1")


def _alpha() -> AlphaSignal:
    return AlphaSignal(
        symbol="MSFT",
        as_of=NOW - timedelta(hours=1),
        signal_type="QUALITY_MOMENTUM",
        expected_excess_return=0.03,
        horizon=20,
        raw_signal=1.0,
        normalized_signal=1.5,
        confidence=0.8,
        confidence_calibrated=True,
        sample_size=120,
        statistical_strength=0.8,
        economic_strength=0.7,
        decay_half_life=20,
        valid_until=NOW + timedelta(days=5),
        data_quality=AlphaDataQuality.VALID,
        pit_valid=True,
        validation_status=AlphaValidationStatus.PRODUCTION_APPROVED,
        model_version="alpha-v1",
        data_version="data-v1",
    )


def _proposal() -> TradeProposal:
    return TradeProposal(
        ticker="MSFT",
        action=TradeAction.INCREASE,
        current_weight=0.05,
        target_weight=0.08,
        delta_weight=0.03,
        estimated_trade_value=3000,
        estimated_cost=3,
        risk_contribution=0.1,
        expected_alpha=0.03,
        confidence=0.8,
        horizon=20,
        reason="optimizer-approved target difference",
        primary_evidence=("alpha-v1",),
        counter_evidence=(),
        model_version="portfolio-v1",
        data_version="data-v1",
        data_quality="VALID",
    )


def test_scanner_cannot_invent_weights_and_quant_only_survives_ai_failure() -> None:
    scanner = DailyOpportunityScanner()
    research = scanner.scan(
        authorization=_authorization(ResearchPurpose.RESEARCH, GateStatus.RESEARCH_ONLY),
        alpha_signals=(_alpha(),),
        proposals=(),
        probability_by_symbol={},
        event_statistics_by_symbol={},
        current_weights={"MSFT": 0.05},
        risk_flags_by_symbol={},
        mode=ScannerMode.QUANT_ONLY,
        ai_ready=False,
    )
    assert research[0].status is CandidateStatus.RESEARCH_ONLY
    assert research[0].target_weight_candidate is None
    assert research[0].ai_readiness == "INTELLIGENCE_DEGRADED"
    approved = scanner.scan(
        authorization=_authorization(
            ResearchPurpose.PORTFOLIO_DECISION, GateStatus.APPROVED
        ),
        alpha_signals=(_alpha(),),
        proposals=(_proposal(),),
        probability_by_symbol={},
        event_statistics_by_symbol={},
        current_weights={"MSFT": 0.05},
        risk_flags_by_symbol={},
        mode=ScannerMode.QUANT_ONLY,
        ai_ready=False,
    )
    assert approved[0].status is CandidateStatus.ACTIONABLE
    assert approved[0].target_weight_candidate == 0.08


def test_event_store_replay_hides_future_information_and_is_deterministic() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repository = IntelligenceRepository(session)
        first = make_event("first", NOW - timedelta(days=2))
        future = make_event("future", NOW + timedelta(days=2))
        repository.upsert_event(first)
        repository.upsert_event(future)
        session.commit()
        replay_one = repository.visible_events(NOW)
        replay_two = repository.visible_events(NOW)
    assert tuple(item.event_id for item in replay_one) == ("first",)
    assert replay_one == replay_two


def test_database_extraction_cache_and_result_store_are_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        cache = DatabaseExtractionCache(
            session, model_version="model-v1", prompt_version="prompt-v1"
        )
        assert cache.get("cache-key") is None
        cache.put("cache-key", "{\"ok\":true}")
        session.flush()
        assert cache.get("cache-key") == "{\"ok\":true}"
        cache.put("cache-key", "ignored")
        repository = IntelligenceRepository(session)
        payload: dict[str, object] = {"status": "READY", "count": 1}
        repository.add_result(
            result_id="result-1",
            result_type="TEST",
            schema_version="v1",
            model_version="model-v1",
            prompt_version="NONE",
            data_cutoff=NOW,
            status="READY",
            payload=payload,
        )
        session.flush()
        repository.add_result(
            result_id="result-1",
            result_type="TEST",
            schema_version="v1",
            model_version="model-v1",
            prompt_version="NONE",
            data_cutoff=NOW,
            status="READY",
            payload=payload,
        )
