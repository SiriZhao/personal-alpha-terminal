from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from personal_alpha_terminal.agents.llm.providers import LLMProviderError
from personal_alpha_terminal.agents.llm.schemas import LLMRequest, LLMResponse
from personal_alpha_terminal.application.daily_orchestrator import DailyQuantOrchestrator
from personal_alpha_terminal.application.forward_evidence import (
    AgenticForwardEvidenceLedger,
    HybridCounterfactualRecord,
    QuantCounterfactualRecord,
    SemanticForwardPredictionRecord,
)
from personal_alpha_terminal.application.forward_shadow_operations import (
    SHADOW_PROVIDER_CACHE_TYPE,
    ForwardShadowOperations,
    ForwardShadowRunLedger,
    PersistentShadowProvider,
    ShadowRunIdentity,
    ShadowRunState,
    build_forward_shadow_dashboard,
    probe_forward_shadow_provider,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.models import Price, SecurityMaster
from personal_alpha_terminal.models.intelligence import IntelligenceResearchResult
from personal_alpha_terminal.terminal.market_sessions import MarketSessionCalendar

DECISION = datetime(2026, 8, 7, 22, tzinfo=UTC)
COLLECTED = datetime(2026, 8, 11, 22, tzinfo=UTC)


class CountingProvider:
    name = "deepseek"
    model = "deepseek-test"

    def __init__(self, *, failure: str | None = None) -> None:
        self.calls = 0
        self.failure = failure

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self.failure is not None:
            raise LLMProviderError("sanitized", category=self.failure)
        content = (
            json.dumps(
                {
                    "status": "ok",
                    "schema_version": "forward-shadow-provider-doctor-v1",
                }
            )
            if request.task_type == "CONNECTIVITY_TEST"
            else '{"status":"cached"}'
        )
        return LLMResponse(
            content=content,
            provider=self.name,
            model=self.model,
            is_mock=False,
            request_id="provider-request-1",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=25,
        )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        runtime_profile="FORWARD_SHADOW_VALIDATION",
        llm_provider="deepseek",
        deepseek_api_key="not-a-real-secret",
        deepseek_model="deepseek-test",
        agentic_shadow_external_enabled=True,
        database_url="sqlite://",
        forward_shadow_lock_path=tmp_path / "shadow.lock",
        forward_outcome_lock_path=tmp_path / "outcomes.lock",
    )


def _identity() -> ShadowRunIdentity:
    return ShadowRunIdentity(
        shadow_run_id="daily-shadow-2026-08-07-test",
        session_id="shadow-session-2026-08-07-test",
        session_date=date(2026, 8, 7),
        decision_timestamp=DECISION,
        provider="deepseek",
        model="deepseek-test",
        code_sha="a" * 40,
    )


def _security(symbol: str, canonical_code: str, exchange: str = "XNAS") -> SecurityMaster:
    available = DECISION - timedelta(days=30)
    return SecurityMaster(
        canonical_code=canonical_code,
        symbol=symbol,
        name=symbol,
        market="US",
        exchange=exchange,
        asset_type="stock" if symbol != "SPY" else "etf",
        currency="USD",
        timezone="America/New_York",
        list_date=date(2010, 1, 4),
        delist_date=None,
        is_active=True,
        source="fixture_archive",
        provider="fixture_primary",
        available_time=available,
        ingested_time=available,
    )


def _price(stock_id: int, trade_date: date, value: str) -> Price:
    available = datetime.combine(trade_date, datetime.min.time(), tzinfo=UTC) + timedelta(
        hours=22
    )
    close = Decimal(value)
    return Price(
        stock_id=stock_id,
        trade_date=trade_date,
        open=close,
        high=close,
        low=close,
        close=close,
        adjusted_close=close,
        volume=1_000_000,
        asset_type="stock",
        volume_unit="share",
        price_currency="USD",
        share_unit=Decimal("1"),
        price_type="unadjusted_ohlcv",
        source="yahoo_finance",
        provider="fixture.yahoo",
        adjustment_method="yahoo_adjusted_close",
        event_time=available - timedelta(minutes=30),
        available_time=available,
        ingested_at=available,
    )


def _prediction() -> SemanticForwardPredictionRecord:
    return SemanticForwardPredictionRecord(
        prediction_id="prediction-round59-1",
        observation_id="security-observation-round59-1",
        counterfactual_observation_id="portfolio-observation-round59-1",
        decision_timestamp=DECISION,
        information_cutoff=DECISION,
        security_id="PERM:AAA",
        company_id="company-aaa",
        symbol="AAA",
        symbol_as_of_time=DECISION - timedelta(days=30),
        quant_score=0.8,
        quant_probability=0.6,
        expected_alpha_value=0.02,
        expected_alpha_semantics="DETERMINISTIC_QUANT_ENGINE_ESTIMATE",
        event_ids=("event-1",),
        event_provenance=({"event_id": "event-1"},),
        llm_provider="deepseek",
        llm_model="deepseek-test",
        llm_schema_version="company-thesis-v1",
        prompt_version="company-thesis-v2",
        llm_inference_status="VALID",
        llm_request_hash="request-1",
        llm_response_hash="response-1",
        structured_thesis={"symbol": "AAA"},
        debate_result={"decision": "AGREE"},
        semantic_score=0.5,
        semantic_alpha=0.001,
        shadow_lambda=0.2,
        quant_target_weight=0.5,
        hybrid_target_weight=0.6,
        quant_risk_result={"status": "VALID", "regime": "RISK_ON"},
        hybrid_risk_result={"status": "VALID"},
        data_snapshot_identity={"market_data_hash": "data-1"},
        evidence_origin="REAL_FORWARD",
        status="SHADOW",
    )


def _counterfactuals() -> tuple[QuantCounterfactualRecord, HybridCounterfactualRecord]:
    common = {
        "observation_id": "portfolio-observation-round59-1",
        "decision_timestamp": DECISION,
        "information_cutoff": DECISION,
        "security_ids": ("PERM:AAA",),
        "universe_identity": "universe-1",
        "evaluation_horizon": "1d",
        "execution_assumptions_hash": "execution-1",
        "transaction_cost_model": "cost-1",
        "slippage_model": "slippage-1",
        "benchmark_convention": "SPY",
        "data_version": "data-1",
        "current_weights": {"PERM:AAA": 0.4},
        "risk_result": {"status": "VALID"},
        "optimizer_result": {"status": "VALID"},
    }
    return (
        QuantCounterfactualRecord(
            counterfactual_id="quant-round59-1",
            target_weights={"PERM:AAA": 0.5},
            **common,
        ),
        HybridCounterfactualRecord(
            counterfactual_id="hybrid-round59-1",
            target_weights={"PERM:AAA": 0.6},
            **common,
        ),
    )


def test_external_shadow_requires_explicit_profile_and_provider() -> None:
    with pytest.raises(ValueError, match="FORWARD_SHADOW_VALIDATION"):
        Settings(
            _env_file=None,
            agentic_shadow_external_enabled=True,
            llm_provider="deepseek",
            deepseek_api_key="x",
        )
    with pytest.raises(ValueError, match="explicit external"):
        Settings(
            _env_file=None,
            runtime_profile="FORWARD_SHADOW_VALIDATION",
            agentic_shadow_external_enabled=True,
            llm_provider="auto",
            deepseek_api_key="x",
        )


def test_provider_response_cache_is_idempotent_and_not_forward_evidence(
    session_factory,
) -> None:
    provider = CountingProvider()
    cached = PersistentShadowProvider(provider, session_factory)
    request = LLMRequest(
        system_prompt="Return JSON.",
        user_prompt='{"security":"AAA"}',
        temperature=0.0,
        prompt_version="company-thesis-v2",
        task_type="COMPANY_THESIS",
        as_of=DECISION,
    )
    assert cached.generate(request).content == '{"status":"cached"}'
    assert cached.generate(request).content == '{"status":"cached"}'
    assert provider.calls == 1
    with session_factory() as session:
        cache_count = session.scalar(
            select(func.count())
            .select_from(IntelligenceResearchResult)
            .where(IntelligenceResearchResult.result_type == SHADOW_PROVIDER_CACHE_TYPE)
        )
        assert cache_count == 1
        assert AgenticForwardEvidenceLedger(session).records(
            "SEMANTIC_FORWARD_PREDICTION"
        ) == ()


def test_forward_profile_does_not_enable_provider_from_key_alone(
    session_factory,
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        runtime_profile="FORWARD_SHADOW_VALIDATION",
        llm_provider="deepseek",
        deepseek_api_key="present-but-not-authority",
        agentic_shadow_external_enabled=False,
        database_url="sqlite://",
        daily_pipeline_report_path=tmp_path / "daily.md",
    )
    orchestrator = DailyQuantOrchestrator(session_factory, settings)
    provider, model, configured, connectivity = orchestrator._configured_llm_identity()
    assert provider == "deepseek"
    assert model == "DISABLED"
    assert configured is False
    assert connectivity == "DISABLED_BY_EXPLICIT_GATE"


def test_run_state_allows_degraded_resume_but_never_backward_or_post_complete(
    session_factory,
) -> None:
    identity = _identity()
    with session_factory.begin() as session:
        ledger = ForwardShadowRunLedger(session)
        assert ledger.append(identity, ShadowRunState.CREATED, observed_at=DECISION)
        assert ledger.append(
            identity,
            ShadowRunState.QUANT_COMPLETED,
            observed_at=DECISION + timedelta(seconds=1),
        )
        assert ledger.append(
            identity,
            ShadowRunState.DEGRADED,
            metadata={"reason": "TIMEOUT"},
            observed_at=DECISION + timedelta(seconds=2),
        )
        assert ledger.append(
            identity,
            ShadowRunState.EVENTS_RESOLVED,
            observed_at=DECISION + timedelta(seconds=3),
        )
        assert ledger.append(
            identity,
            ShadowRunState.COMPLETE,
            observed_at=DECISION + timedelta(seconds=4),
        )
        with pytest.raises(ValueError, match="terminal"):
            ledger.append(identity, ShadowRunState.LLM_REQUESTED)


def test_resume_blocks_when_code_provenance_changes(
    session_factory,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    config = EffectiveRuntimeConfig(settings=settings, portfolio_id=None)
    identity = _identity()
    with session_factory.begin() as session:
        ForwardShadowRunLedger(session).append(
            identity,
            ShadowRunState.CREATED,
            observed_at=DECISION,
        )
    service = ForwardShadowOperations(session_factory, config, now=lambda: COLLECTED)
    with pytest.raises(ValueError, match="BLOCK_REQUIRES_NEW_RUN"):
        service.resume(shadow_run_id=identity.shadow_run_id)


def test_provider_live_smoke_is_not_persisted_as_forward_evidence(
    session_factory,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    provider = CountingProvider()
    health = probe_forward_shadow_provider(
        settings,
        live=True,
        provider=provider,
        status_path=tmp_path / "provider-status.json",
        now=DECISION,
    )
    assert health.connectivity == "AVAILABLE"
    assert health.eligible_for_forward_evidence is False
    assert health.eligible_for_promotion is False
    with session_factory() as session:
        assert AgenticForwardEvidenceLedger(session).records(
            "SEMANTIC_FORWARD_PREDICTION"
        ) == ()


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("AUTHENTICATION_FAILED", "AUTH_FAILURE"),
        ("RATE_LIMITED", "RATE_LIMIT"),
        ("TIMEOUT", "TIMEOUT"),
        ("PROVIDER_UNAVAILABLE", "PROVIDER_ERROR"),
        ("REQUEST_FAILED", "NETWORK_ERROR"),
    ],
)
def test_provider_failure_classification_is_sanitized(
    tmp_path: Path,
    failure: str,
    expected: str,
) -> None:
    health = probe_forward_shadow_provider(
        _settings(tmp_path),
        live=True,
        provider=CountingProvider(failure=failure),
        status_path=tmp_path / f"{failure}.json",
        now=DECISION,
    )
    assert health.connectivity == "UNAVAILABLE"
    assert health.last_failure == expected


def test_calendar_maturity_uses_exchange_sessions_not_calendar_days() -> None:
    calendar = MarketSessionCalendar()
    friday = date(2026, 9, 4)
    assert calendar.advance_trading_sessions(friday, 1) == date(2026, 9, 8)
    assert calendar.trading_session_window(friday, date(2026, 9, 8)) == (
        date(2026, 9, 4),
        date(2026, 9, 8),
    )


def test_outcome_collector_appends_exact_real_outcome_once_and_keeps_prediction_immutable(
    session_factory,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    config = EffectiveRuntimeConfig(settings=settings, portfolio_id=None)
    with session_factory.begin() as session:
        aaa = _security("AAA", "PERM:AAA")
        spy = _security("SPY", "PERM:SPY", "ARCX")
        session.add_all((aaa, spy))
        session.flush()
        session.add_all(
            (
                _price(aaa.id, date(2026, 8, 7), "100"),
                _price(aaa.id, date(2026, 8, 10), "110"),
                _price(spy.id, date(2026, 8, 7), "500"),
                _price(spy.id, date(2026, 8, 10), "505"),
            )
        )
        ledger = AgenticForwardEvidenceLedger(session)
        ledger.append_prediction(_prediction())
        quant, hybrid = _counterfactuals()
        ledger.append_quant_counterfactual(quant)
        ledger.append_hybrid_counterfactual(hybrid)
        before = ledger.records("SEMANTIC_FORWARD_PREDICTION")
    service = ForwardShadowOperations(
        session_factory,
        config,
        now=lambda: COLLECTED,
    )
    first = service.collect_outcomes(collected_at=COLLECTED)
    second = service.collect_outcomes(collected_at=COLLECTED)
    assert first.outcomes_appended == 1
    assert first.promotion.real_forward_n == 1
    assert first.promotion.paired_sample_n == 1
    assert second.outcomes_appended == 0
    assert second.duplicate_outcomes == 1
    with session_factory() as session:
        ledger = AgenticForwardEvidenceLedger(session)
        assert ledger.records("SEMANTIC_FORWARD_PREDICTION") == before
        outcome = ledger.records("SEMANTIC_FORWARD_OUTCOME")[0]
        assert outcome["hybrid_net_return"] > outcome["quant_net_return"]
        assert outcome["evidence_origin"] == "REAL_FORWARD"


def test_zero_evidence_dashboard_uses_insufficient_evidence_not_zero_estimates(
    session_factory,
) -> None:
    with session_factory() as session:
        dashboard = build_forward_shadow_dashboard(
            session,
            settings=Settings(_env_file=None),
            evaluated_at=DECISION,
        )
    promotion = dashboard["promotion_evidence"]
    authority = dashboard["authority"]
    assert promotion["promotion_reason"] == "NO_FORWARD_EVIDENCE"
    assert promotion["mean_incremental_net_alpha"] is None
    assert promotion["confidence_interval"] is None
    assert authority["production_lambda"] == 0.0
    assert authority["production_llm_authority"] == "0%"
