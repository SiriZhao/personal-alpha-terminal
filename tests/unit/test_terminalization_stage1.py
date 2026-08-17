from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.agents.llm.providers import LLMProviderError
from personal_alpha_terminal.agents.llm.schemas import LLMRequest, LLMResponse
from personal_alpha_terminal.application.daily_orchestrator import DailyQuantOrchestrator
from personal_alpha_terminal.application.daily_result import (
    DecisionReadiness,
    StageStatus,
)
from personal_alpha_terminal.application.data_certification import DailyDataCertification
from personal_alpha_terminal.application.forward_evidence import (
    AgenticForwardEvidenceLedger,
)
from personal_alpha_terminal.application.quant_daily_service import (
    ShadowQuantContext,
    TodayRecommendation,
    TodayResult,
)
from personal_alpha_terminal.application.universe import MINIMUM_US_RESEARCH_UNIVERSE
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.market_data.schemas import (
    DailyUpdateReport,
    InstrumentUpdateResult,
)
from personal_alpha_terminal.intelligence.schemas import (
    BacktestSafety,
    EventDirection,
    EventEvidence,
    EventType,
    RawInformation,
    UnifiedEvent,
)
from personal_alpha_terminal.intelligence.storage import IntelligenceRepository
from personal_alpha_terminal.models import (
    DataSnapshotManifest,
    MarketUniverseMember,
    Portfolio,
    Stock,
)
from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
    PortfolioConstructionEngine,
)
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantInput,
    DailyQuantPipeline,
    PipelineStage,
)
from personal_alpha_terminal.quant_engine.risk.budget import PortfolioRiskState
from personal_alpha_terminal.quant_engine.risk.model import AssetRiskMetadata
from personal_alpha_terminal.quant_engine.risk.stress import StressRiskConfig
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    StrategyFactorSnapshot,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)
from personal_alpha_terminal.terminal.daily_renderer import capture_daily_quant_result

NOW = datetime(2026, 8, 8, 21, tzinfo=UTC)
SYMBOLS = ("A", "B", "C", "D")


def _authorization():
    request = ResearchDataRequest(
        ResearchPurpose.PORTFOLIO_DECISION,
        "US",
        "stock",
        date(2025, 1, 1),
        date(2026, 8, 7),
        NOW,
        "point_in_time_total_return",
        "universe-v1",
        timedelta(days=5),
    )
    evidence = ResearchDataEvidence(
        "US",
        "stock",
        "passed",
        "primary",
        "fixture-adapter",
        ("source-a", "source-b"),
        NOW - timedelta(days=1),
        "certified",
        "point_in_time_total_return",
        "universe-v1",
        NOW - timedelta(days=2),
        True,
        True,
        0.0,
        0.0,
        0.0,
        0.0,
        "data-v1",
        True,
        True,
        True,
        True,
    )
    return ResearchDataGate().authorize(request, evidence, evaluated_at=NOW)


def _actual_quant_case():
    rng = np.random.default_rng(11)
    market = rng.normal(0.0003, 0.009, 180)
    returns = pd.DataFrame(
        {symbol: 0.75 * market + rng.normal(0.0003, 0.006, 180) for symbol in SYMBOLS},
        index=pd.bdate_range("2025-11-24", periods=180),
    )
    benchmark = pd.Series(market, index=returns.index)
    metadata = tuple(
        AssetRiskMetadata(
            symbol,
            "Technology" if index < 2 else "Healthcare",
            50_000_000 + index * 5_000_000,
            0.0,
        )
        for index, symbol in enumerate(SYMBOLS)
    )
    signals = tuple(
        AlphaSignal(
            symbol,
            NOW - timedelta(hours=1),
            "medium_term_momentum",
            0.01 + index * 0.001,
            20,
            1.0,
            0.8,
            0.8,
            True,
            200,
            0.8,
            0.7,
            40.0,
            NOW + timedelta(days=5),
            AlphaDataQuality.VALID,
            True,
            AlphaValidationStatus.PRODUCTION_APPROVED,
            "alpha-v1",
            "data-v1",
        )
        for index, symbol in enumerate(SYMBOLS)
    )
    constraints = PortfolioConstraints(
        maximum_position_weight=0.30,
        maximum_sector_weight=0.60,
        maximum_cluster_weight=0.70,
        maximum_hhi=0.35,
        minimum_cash_weight=0.15,
        maximum_gross_exposure=0.85,
        target_annualized_volatility=0.30,
        maximum_beta=1.2,
        maximum_turnover=0.90,
        maximum_size_exposure=0.80,
        no_trade_band=0.002,
        minimum_rebalance_weight=0.003,
        minimum_trade_value=50,
        risk_aversion=2.0,
        turnover_penalty=0.001,
        model_validation_id="locked-oos-fixture",
    )
    pipeline = DailyQuantPipeline(
        construction=PortfolioConstructionEngine(constraints),
        stress_config=StressRiskConfig(
            production_validated=True,
            validation_id="locked-oos-stress-fixture",
            maximum_single_name_loss=0.10,
            maximum_sector_loss=0.20,
        ),
    )
    inputs = DailyQuantInput(
        _authorization(),
        NOW,
        signals,
        returns,
        benchmark,
        metadata,
        {},
        1_000_000,
        PortfolioRiskState(-0.01, 0.12, 0.0, 0.0, 0.25, 0.25),
        None,
        True,
        "universe-v1",
        "CERTIFIED",
    )
    return pipeline.run(inputs), inputs


def _actual_quant_output():
    return _actual_quant_case()[0]


def _workflow_result() -> TodayResult:
    output, inputs = _actual_quant_case()
    assert output.target is not None
    execution = NOW + timedelta(days=2)
    recommendations = tuple(
        TodayRecommendation(
            f"rec-{item.ticker}",
            item.ticker,
            "ADD" if item.action.value == "INCREASE" else item.action.value,
            item.current_weight,
            item.target_weight,
            item.delta_weight,
            100,
            item.estimated_cost,
            item.expected_alpha,
            item.confidence,
            "; ".join(item.counter_evidence),
            item.model_version,
            item.data_version,
            execution,
            execution + timedelta(days=7),
            item.estimated_trade_value,
            item.risk_contribution,
            item.reason,
            item.data_quality,
        )
        for item in output.trades
    )
    factors = tuple(
        StrategyFactorSnapshot(
            symbol,
            {"momentum": 0.8 - index * 0.1, "trend": 0.6},
            0.7 - index * 0.05,
            index + 1,
            0.01 + index * 0.001,
            0.8,
            "VALID",
        )
        for index, symbol in enumerate(SYMBOLS)
    )
    return TodayResult(
        17,
        NOW,
        "POST_CLOSE_DECISION",
        "CERTIFIED_AS_OF_DECISION",
        "GENERATED",
        "APPROVED",
        "APPROVED",
        "TARGET_COMPUTED",
        "SCORE_UNAVAILABLE",
        sum(output.target.target_weights.values()),
        output.target.cash_weight,
        recommendations,
        None,
        (),
        (),
        "data-v1",
        "alpha-v1",
        "config-v1",
        output.stages,
        factors,
        output.risk,
        output.target,
        output.trades,
        1_000_000,
        {},
        NOW,
        len(SYMBOLS),
        ("source-a", "source-b"),
        ("quality",),
        "SPY",
        180,
        0.12,
        0.18,
        shadow_context=ShadowQuantContext(
            inputs=inputs,
            validation_id=output.target.model_validation_id,
            operational_mode=False,
        ),
    )


class _SafeDataService:
    def __init__(self, *_args, **_kwargs) -> None:
        self.manifest = SimpleNamespace(
            end_date=date(2026, 8, 7),
            missingness_summary={"overall": 0.0},
            provider_name="fixture-primary+fixture-secondary",
        )

    def get_data_readiness(self, **_kwargs):
        return SimpleNamespace(code="CERTIFIED", technical_reason="fixture certified")

    def latest_manifest(self):
        return self.manifest

    def daily_certification(self, **_kwargs):
        return DailyDataCertification(
            status=StageStatus.PASS,
            snapshot_id="fixture-snapshot",
            data_hash="d" * 64,
            provider="fixture-primary",
            fallback_provider="fixture-secondary",
            requested_symbols=SYMBOLS,
            received_symbols=SYMBOLS,
            primary_valid_symbols=SYMBOLS,
            secondary_checked_symbols=SYMBOLS,
            certified_symbols=SYMBOLS,
            rejected_symbols=(),
            missing_symbols=(),
            optional_missing_symbols=(),
            stale_symbols=(),
            expected_bars=504 * len(SYMBOLS),
            matched_bars=504 * len(SYMBOLS),
            unexpected_bars=0,
            missing_bars=0,
            received_bars=504 * len(SYMBOLS),
            valid_bars=504 * len(SYMBOLS),
            coverage=1.0,
            latest_date=date(2026, 8, 7),
            latest_timestamp=NOW - timedelta(days=1),
            pit_cutoff=NOW - timedelta(days=1),
            latest_completed_session=date(2026, 8, 7),
            decision_timestamp_convention="fixture next-session",
            corporate_action_status="PASS",
            provider_reconciliation="NOT_REQUIRED",
            duplicate_rows=0,
            invalid_ohlc=0,
            nan_counts={"open": 0, "high": 0, "low": 0, "close": 0},
            future_rows=0,
            timezone_violations=0,
            adjustment_status="raw_ohlcv",
            symbol_matrix=(),
            evidence_paths={},
            blockers=(),
            warnings=(),
        )


class _UnsafeDataService(_SafeDataService):
    def daily_certification(self, **_kwargs):
        return replace(
            super().daily_certification(**_kwargs),
            status=StageStatus.FAIL_BLOCKING,
            pit_integrity_status="FAIL",
            blockers=("PIT data cutoff is unavailable",),
        )


class _DegradedDataService(_SafeDataService):
    def daily_certification(self, **_kwargs):
        return replace(
            super().daily_certification(**_kwargs),
            status=StageStatus.PASS_DEGRADED,
            optional_missing_symbols=("OPTIONAL",),
            warnings=("optional symbols missing: OPTIONAL",),
        )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        runtime_profile="TEST",
        database_url="sqlite://",
        daily_pipeline_report_path=tmp_path / "daily.md",
        llm_provider="disabled",
        DEEPSEEK_API_KEY=None,
    )


def _seed_agentic_event(session: Session) -> None:
    published = NOW - timedelta(hours=3)
    observed = NOW - timedelta(hours=2, minutes=55)
    ingested = NOW - timedelta(hours=2, minutes=54)
    session.add(
        Stock(
            canonical_code="PERM:A",
            symbol="A",
            name="A Corporation",
            market="US",
            exchange="XNAS",
            asset_type="stock",
            currency="USD",
            timezone="America/New_York",
            is_active=True,
            source="fixture",
            provider="fixture",
            available_time=NOW - timedelta(days=30),
            ingested_time=NOW - timedelta(days=30),
        )
    )
    raw = RawInformation(
        raw_id="raw-agentic-a",
        source="fixture-news",
        source_identifier="fixture://agentic-a",
        title="A Corporation raises guidance",
        body="A Corporation published higher full-year guidance.",
        issuer_id="company-a",
        issuer_name="A Corporation",
        permanent_security_id="PERM:A",
        ticker_as_of="A",
        issuer_resolution_status="RESOLVED",
        security_mapping_status="MAPPED",
        published_at=published,
        observed_at=observed,
        ingested_at=ingested,
        available_at=observed,
        processed_at=ingested,
        data_cutoff=observed,
    )
    event = UnifiedEvent(
        event_id="event-agentic-a",
        symbol="A",
        entity="A Corporation",
        event_type=EventType.GUIDANCE,
        title=raw.title,
        summary="Management raised its public full-year guidance.",
        published_at=published,
        observed_at=observed,
        effective_at=published,
        ingested_at=ingested,
        source=raw.source,
        source_identifier=raw.source_identifier,
        source_hash=raw.source_hash or "",
        direction=EventDirection.POSITIVE,
        magnitude=0.7,
        surprise=0.6,
        relevance=1.0,
        novelty=0.8,
        confidence=0.9,
        expected_horizon=10,
        evidence=(
            EventEvidence(
                evidence_id="evidence-agentic-a",
                source=raw.source,
                source_identifier=raw.source_identifier,
                source_hash=raw.source_hash or "",
                published_at=published,
                observed_at=observed,
                available_at=observed,
                reference=raw.source_identifier,
                extraction_confidence=0.9,
            ),
        ),
        model_version="fixture-extractor-v1",
        prompt_version="fixture-extraction-v1",
        data_cutoff=observed,
        created_at=ingested,
        backtest_safety=BacktestSafety.BACKTEST_SAFE,
        canonical_cluster_id="cluster-agentic-a",
    )
    repository = IntelligenceRepository(session)
    repository.upsert_raw(raw)
    repository.upsert_event(event)


class _StructuredThesisProvider:
    name = "fixture-external"
    model = "fixture-thesis-v1"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.fail:
            raise LLMProviderError("timeout", category="TIMEOUT")
        user_data = json.loads(request.user_prompt)["USER_DATA"]
        security = user_data["security"]
        event_id = user_data["events"][0]["event_id"]
        return LLMResponse(
            content=json.dumps(
                {
                    "symbol": security["symbol"],
                    "security": security,
                    "stance": "BULLISH",
                    "confidence": 0.8,
                    "event_direction": 0.8,
                    "event_magnitude": 0.7,
                    "market_surprise": 0.6,
                    "novelty": 0.8,
                    "company_relevance": 1.0,
                    "expected_horizon_sessions": 10,
                    "bull_case": "The supplied guidance event supports upside.",
                    "bear_case": "The guidance increase may not persist.",
                    "key_catalysts": ["PUBLIC_GUIDANCE_INCREASE"],
                    "invalidation_conditions": ["GUIDANCE_WITHDRAWN"],
                    "risk_flags": ["EXECUTION_RISK"],
                    "evidence_event_ids": [event_id],
                    "concise_rationale": "The supplied event is positive and material.",
                    "unsupported_claims": [],
                    "source_conflict": False,
                }
            ),
            provider=self.name,
            model=self.model,
            is_mock=False,
            request_id="fixture-request-1",
        )


def test_daily_agentic_shadow_executes_and_provider_failure_preserves_quant(
    session_factory: sessionmaker[Session], tmp_path: Path, monkeypatch
) -> None:
    with session_factory.begin() as session:
        session.add(Portfolio(name="Agentic Ledger", cash_balance=1_000_000))
        _seed_agentic_event(session)
    workflow = _workflow_result()
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.DataService",
        _SafeDataService,
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.ProductionDailyWorkflow.run",
        lambda _self, **_kwargs: workflow,
    )

    provider = _StructuredThesisProvider()
    success = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "success-runs",
        shadow_llm_provider_factory=lambda: provider,
    ).run(decision_time=NOW, refresh=False)
    assert provider.requests
    assert success.hybrid_intelligence is not None
    assert success.hybrid_intelligence["counts"]["real_structured_theses"] == 1
    assert success.hybrid_intelligence["counts"]["real_shadow_llm_decisions"] == 1
    assert success.hybrid_intelligence["counts"]["hybrid_counterfactual_executed"] == 1
    assert success.hybrid_intelligence["invariants"]["production_lambda"] == 0.0
    assert success.hybrid_intelligence["forward_evidence_persistence"] == {
        "predictions": 1,
        "counterfactuals": 2,
        "promotion_evaluations": 1,
    }
    assert success.hybrid_intelligence["promotion"]["real_forward_n"] == 0
    assert success.hybrid_intelligence["promotion"]["production_lambda"] == 0.0
    with session_factory() as session:
        ledger = AgenticForwardEvidenceLedger(session)
        assert len(ledger.records("SEMANTIC_FORWARD_PREDICTION")) == 1
        assert len(ledger.records("QUANT_COUNTERFACTUAL")) == 1
        assert len(ledger.records("HYBRID_COUNTERFACTUAL")) == 1
    assert success.hybrid_intelligence["shadow_pipeline"]["deterministic_risk_evaluated"] is True
    assert [(item.symbol, item.action) for item in success.final_decisions] == [
        (item.symbol, item.action) for item in workflow.recommendations
    ]
    outbound = json.loads(provider.requests[0].user_prompt)["USER_DATA"]
    serialized = json.dumps(outbound, sort_keys=True)
    assert "cash_balance" not in serialized
    assert "account_id" not in serialized
    assert "order_history" not in serialized

    failing_provider = _StructuredThesisProvider(fail=True)
    degraded = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "degraded-runs",
        shadow_llm_provider_factory=lambda: failing_provider,
    ).run(decision_time=NOW, refresh=False)
    assert failing_provider.requests
    assert degraded.hybrid_intelligence is not None
    assert degraded.hybrid_intelligence["degradation"]["by_symbol"]["A"] == ["TIMEOUT"]
    assert degraded.hybrid_intelligence["counts"]["real_shadow_llm_decisions"] == 0
    assert degraded.hybrid_intelligence["invariants"]["production_lambda"] == 0.0
    assert [(item.symbol, item.action) for item in degraded.final_decisions] == [
        (item.symbol, item.action) for item in workflow.recommendations
    ]


def test_actual_quant_pipeline_flows_to_terminal_without_recalculation(
    session_factory: sessionmaker[Session], tmp_path: Path, monkeypatch
) -> None:
    with session_factory.begin() as session:
        session.add(Portfolio(name="Real Ledger", cash_balance=1_000_000))
    workflow = _workflow_result()
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.DataService",
        _SafeDataService,
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.ProductionDailyWorkflow.run",
        lambda _self, **_kwargs: workflow,
    )
    result = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "runs",
    ).run(decision_time=NOW, refresh=False)

    assert result.decision_readiness is DecisionReadiness.READY
    assert result.llm_status == "OPTIONAL_UNAVAILABLE/SHADOW/disabled/NOT_CONFIGURED"
    assert [(item.symbol, item.action) for item in result.final_decisions] == [
        (item.symbol, item.action) for item in workflow.recommendations
    ]
    execution_symbols = {leg.symbol for leg in result.execution_plan.legs}
    assert all(
        item.symbol in execution_symbols for item in result.final_decisions if item.action != "HOLD"
    )
    rendered = capture_daily_quant_result(result, width=120)
    narrow = capture_daily_quant_result(result, width=80)
    assert "FINAL VALIDATED DECISIONS" in rendered
    assert "DATA CERTIFICATION" in rendered
    assert "PIT / UNIVERSE" in rendered
    assert "CANDIDATE ≠ TRADE" in rendered
    for decision in result.final_decisions:
        assert decision.symbol in rendered
        assert decision.action in rendered
    assert "MANUAL EXECUTION REQUIRED" in rendered
    assert "TODAY SUMMARY" in narrow
    assert list((tmp_path / "runs").glob("*.json"))
    assert result.certificate_path is not None
    certificate = Path(result.certificate_path)
    assert certificate.exists()
    certificate_payload = json.loads(certificate.read_text(encoding="utf-8"))
    snapshot = json.loads(
        next((tmp_path / "runs").glob(f"*_{result.run_id}.json")).read_text(encoding="utf-8")
    )
    assert certificate_payload["run_id"] == snapshot["run_id"] == result.run_id
    assert certificate_payload["classification"] == result.run_classification
    assert certificate_payload["research_certification_state"] == (
        result.research_certification_state
    )
    assert certificate_payload["operational_authorization"] == (
        result.operational_policy_decision
    )
    assert certificate_payload["signal_authorization_class"]
    assert certificate_payload["probability_influence"] in {0.0, 1.0}
    assert certificate_payload["llm_mode"] == "SHADOW"
    assert certificate_payload["auto_execution"] is False
    assert certificate_payload["manual_execution_only"] is True


def test_blocked_data_certificate_preserves_real_certification_evidence(
    session_factory: sessionmaker[Session], tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.DataService",
        _UnsafeDataService,
    )
    result = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "runs",
    ).run(decision_time=NOW, refresh=False)

    assert not result.actionable
    certificate = json.loads(Path(result.certificate_path or "").read_text(encoding="utf-8"))
    evidence = certificate["data_certification"]
    assert evidence["requested_symbols"] == list(SYMBOLS)
    assert certificate["provenance"]["data_hash"] == "d" * 64
    assert next(item for item in result.stages if item.name == "PORTFOLIO").status is (
        StageStatus.FAIL_BLOCKING
    )
    assert any(item.rejected_by == "PORTFOLIO" for item in result.rejected_signals)
    assert evidence["received_symbols"] == list(SYMBOLS)
    assert evidence["valid_bars"] == 504 * len(SYMBOLS)
    assert evidence["provider_reconciliation"] == "NOT_REQUIRED"
    assert evidence["snapshot_id"] == "fixture-snapshot"


def test_optional_data_degradation_does_not_block_required_quant_chain(
    session_factory: sessionmaker[Session], tmp_path: Path, monkeypatch
) -> None:
    with session_factory.begin() as session:
        session.add(Portfolio(name="Real Ledger", cash_balance=1_000_000))
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.DataService",
        _DegradedDataService,
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.ProductionDailyWorkflow.run",
        lambda _self, **_kwargs: _workflow_result(),
    )
    result = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "runs",
    ).run(decision_time=NOW, refresh=False)

    data_stage = next(item for item in result.stages if item.name == "DATA")
    assert data_stage.status is StageStatus.PASS_DEGRADED
    assert result.actionable, tuple(
        (item.name, item.status.value, item.message) for item in result.stages
    )


def test_data_gate_failure_does_not_rollback_sync_manifest_or_universe(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    report = DailyUpdateReport(
        started_on=date(2026, 8, 1),
        results=tuple(
            InstrumentUpdateResult(
                symbol=asset.ticker,
                market="US",
                source="fixture-primary",
                provider="fixture.download",
                status="success",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 8, 7),
                fetched_count=22,
                valid_count=22,
                inserted_count=22,
            )
            for asset in MINIMUM_US_RESEARCH_UNIVERSE
        ),
        provider_reconciled=True,
        corporate_action_certified=True,
    )
    result = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "runs",
        sync_runner=lambda _session, _start, _end: report,
    ).run(decision_time=NOW, refresh=True)

    assert not result.actionable
    with session_factory() as session:
        assert session.query(DataSnapshotManifest).count() == 1
        assert session.query(MarketUniverseMember).count() == len(MINIMUM_US_RESEARCH_UNIVERSE)


def test_missing_portfolio_and_stale_data_fail_closed(
    session_factory: sessionmaker[Session], tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.DataService",
        _SafeDataService,
    )
    research_only = replace(
        _workflow_result(),
        status="BLOCKED",
        portfolio_status="NOT_INITIALIZED",
        recommendations=(),
        target=None,
        trades=(),
        risk=None,
        blockers=("PORTFOLIO NOT INITIALIZED; run portfolio-init or portfolio-import",),
        pipeline_stages=(
            PipelineStage("Data Quality Gate", "VALID", "CERTIFIED"),
            PipelineStage("PIT Universe", "VALID", "universe-v1"),
            PipelineStage("Point-in-Time Inputs", "VALID", "no future observations"),
            PipelineStage("Feature Engine", "VALID", "4 PIT feature rows"),
            PipelineStage("Factor Engine", "VALID", "4 factor rows"),
            PipelineStage("Alpha Signals", "VALID", "4 approved signals"),
            PipelineStage(
                "Portfolio Construction",
                "BLOCKED",
                "PORTFOLIO NOT INITIALIZED",
            ),
        ),
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.ProductionDailyWorkflow.run",
        lambda _self, **_kwargs: research_only,
    )
    missing = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "missing",
    ).run(decision_time=NOW, refresh=False)
    assert missing.decision_readiness is DecisionReadiness.NOT_ACTIONABLE
    assert not missing.final_decisions
    assert any("PORTFOLIO NOT INITIALIZED" in item for item in missing.blockers)
    assert next(item for item in missing.stages if item.name == "FACTOR").status is StageStatus.PASS
    assert missing.execution_plan.status == "BLOCKED"
    missing_rendered = capture_daily_quant_result(missing)
    assert "NOT_ACTIONABLE" in missing_rendered
    assert "NO_ACTION" not in missing_rendered
    assert missing.run_classification == "VALID_ANALYSIS_NON_ACTIONABLE"
    assert missing.diagnostic_analysis_complete
    assert "VALID QUANT ANALYSIS" in missing_rendered

    class _Stale(_SafeDataService):
        def get_data_readiness(self, **_kwargs):
            return SimpleNamespace(code="STALE", technical_reason="latest bar is stale")

        def daily_certification(self, **_kwargs):
            return replace(
                super().daily_certification(),
                status=StageStatus.FAIL_BLOCKING,
                stale_symbols=("A",),
                blockers=("required symbols are stale: A",),
            )

    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.DataService", _Stale
    )
    stale = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "stale",
    ).run(decision_time=NOW, refresh=False)
    assert stale.decision_readiness is DecisionReadiness.NOT_ACTIONABLE
    assert not stale.final_decisions
    assert next(item for item in stale.stages if item.name == "DATA").status is StageStatus.FAIL


def test_pit_or_risk_failure_never_reaches_execution_plan(
    session_factory: sessionmaker[Session], tmp_path: Path, monkeypatch
) -> None:
    with session_factory.begin() as session:
        session.add(Portfolio(name="Real Ledger", cash_balance=1_000_000))
    base = _workflow_result()
    blocked = replace(
        base,
        status="BLOCKED",
        recommendations=(),
        blockers=("PIT validation failed before risk model",),
        pipeline_stages=(
            PipelineStage("Data Quality Gate", "VALID", "CERTIFIED"),
            PipelineStage("PIT Universe", "BLOCKED", "PIT validation failed before risk model"),
        ),
        risk=None,
        target=None,
        trades=(),
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.DataService",
        _SafeDataService,
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.ProductionDailyWorkflow.run",
        lambda _self, **_kwargs: blocked,
    )
    result = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "blocked",
    ).run(decision_time=NOW, refresh=False)

    assert result.decision_readiness is DecisionReadiness.NOT_ACTIONABLE
    assert result.final_decisions == ()
    assert result.execution_plan.legs == ()
    assert result.execution_plan.status == "BLOCKED"


def test_calendar_resolves_weekend_and_dst_without_llm_dependency(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    orchestrator = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "runs",
    )
    saturday = datetime(2026, 8, 8, 12, tzinfo=UTC)
    winter = datetime(2026, 1, 15, 15, tzinfo=UTC)
    summer = datetime(2026, 7, 15, 14, tzinfo=UTC)
    saturday_state = orchestrator._calendar.classify(saturday)
    winter_state = orchestrator._calendar.classify(winter)
    summer_state = orchestrator._calendar.classify(summer)

    assert saturday_state.trade_date == date(2026, 8, 10)
    assert winter_state.timestamp_et.utcoffset() != summer_state.timestamp_et.utcoffset()
    assert _settings(tmp_path).llm_provider == "disabled"


def test_daily_uses_sanitized_llm_runtime_status_without_quant_influence(
    session_factory: sessionmaker[Session], tmp_path: Path, monkeypatch
) -> None:
    status_path = tmp_path / "llm-runtime-status.json"
    status_path.write_text(
        json.dumps(
            {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "base_url": "https://api.deepseek.com",
                "credential": "PRESENT",
                "connectivity": "AVAILABLE",
                "last_successful_call": NOW.isoformat(),
                "latency_ms": 25,
                "production_influence": "NONE",
                "error_classification": None,
                "checked_at": NOW.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        runtime_profile="TEST",
        database_url="sqlite://",
        daily_pipeline_report_path=tmp_path / "daily.md",
        llm_provider="disabled",
        DEEPSEEK_API_KEY="unit-test-key",
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.DataService",
        _SafeDataService,
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.ProductionDailyWorkflow.run",
        lambda _self, **_kwargs: _workflow_result(),
    )

    result = DailyQuantOrchestrator(
        session_factory,
        settings,
        snapshot_root=tmp_path / "runs",
        llm_runtime_status_path=status_path,
    ).run(decision_time=NOW, refresh=False)
    stage = next(item for item in result.stages if item.name == "LLM_INTELLIGENCE")

    assert stage.status is StageStatus.PASS_DEGRADED
    assert stage.metadata["provider"] == "deepseek"
    assert stage.metadata["model"] == "deepseek-v4-flash"
    assert stage.metadata["connectivity"] == "AVAILABLE"
    assert stage.metadata["production_influence"] is False
    assert stage.metadata["advisory_quant_impact"] == "NONE"
    assert result.provenance["llm_model"] == (
        "deepseek/deepseek-v4-flash/AVAILABLE/INFLUENCE_NONE"
    )
    assert "AVAILABLE" in capture_daily_quant_result(result)


def test_invalid_stored_policy_renders_blocked_explanation(
    session_factory: sessionmaker[Session], tmp_path: Path, monkeypatch
) -> None:
    workflow = replace(
        _workflow_result(),
        status="BLOCKED",
        recommendations=(),
        operational_policy_id="stored-policy-id",
        operational_policy_decision="ALLOW_PROVISIONAL",
        operational_policy_effective=False,
        operational_policy_reason="OPERATIONAL_POLICY_IDENTITY_MISMATCH",
        operationally_allowed=False,
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.DataService",
        _SafeDataService,
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.ProductionDailyWorkflow.run",
        lambda _self, **_kwargs: workflow,
    )

    result = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "runs",
    ).run(decision_time=NOW, refresh=False)
    rendered = capture_daily_quant_result(result)

    assert "stored Operational Policy is not effective" in rendered
    assert "OPERATIONAL_POLICY_IDENTITY_MISMATCH" in rendered
    assert "Current advice is allowed by an explicit Operational Policy" not in rendered


def test_no_action_requires_complete_certified_pipeline(
    session_factory: sessionmaker[Session], tmp_path: Path, monkeypatch
) -> None:
    with session_factory.begin() as session:
        session.add(Portfolio(name="Real Ledger", cash_balance=1_000_000))
    complete = replace(
        _workflow_result(),
        status="NO_DECISION",
        recommendations=(),
        trades=(),
        no_rebalance_reason="inside validated no-trade band",
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.DataService",
        _SafeDataService,
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.ProductionDailyWorkflow.run",
        lambda _self, **_kwargs: complete,
    )
    result = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "no-action",
    ).run(decision_time=NOW, refresh=False)
    assert result.actionable, tuple(
        (item.name, item.status.value, item.message) for item in result.stages
    )
    assert result.run_classification == "VALID_ANALYSIS_ACTIONABLE_CERTIFIED"
    assert "CERTIFIED ACTIONABLE ANALYSIS" in capture_daily_quant_result(result)
