"""ROUND79 real-forward five-policy ledger regressions."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from personal_alpha_terminal.application.forward_competition import (
    ForwardCompetitionLedger,
    ForwardCompetitionOutcome,
    append_daily_forward_competition,
    build_forward_competition_decision_set,
    competition_dashboard,
)
from personal_alpha_terminal.application.forward_shadow_operations import (
    ForwardShadowOperations,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.models import Price, SecurityMaster
from personal_alpha_terminal.research.portfolio_competition import (
    EvidenceClass,
    OutcomeRecord,
    OutcomeStatus,
    PortfolioVariant,
)

DECISION = datetime(2026, 8, 7, 22, tzinfo=UTC)
COLLECTED = datetime(2026, 8, 11, 22, tzinfo=UTC)


def _workflow() -> SimpleNamespace:
    return SimpleNamespace(
        decision_time=DECISION,
        data_cutoff=DECISION,
        target=SimpleNamespace(target_weights={"AAA": 0.60}),
        current_weights={"AAA": 0.40},
        probability_counterfactual={
            "AAA": {
                "target_without_probability": 0.50,
                "target_with_probability": 0.60,
            }
        },
        risk={"status": "PASS"},
        universe_snapshot_id="US-PIT-2026-08-07",
        universe_count=1,
        data_hash="market-data-2026-08-07",
        model_hash="production-quant-v1",
        config_hash="config-v1",
        strategy_version="production-quant-v1",
        benchmark_symbol="SPY",
    )


def _hybrid() -> dict[str, object]:
    return {
        "actions": [{"symbol": "AAA", "hybrid_target": 0.55}],
        "shadow_pipeline": {"status": "PASS", "manual_only": True},
    }


def _evidence() -> SimpleNamespace:
    return SimpleNamespace(
        companies={
            "AAA": SimpleNamespace(
                security=SimpleNamespace(permanent_security_id="PERM:AAA", symbol="AAA")
            )
        }
    )


def _decision_set():
    return build_forward_competition_decision_set(
        workflow=_workflow(),
        hybrid_document=_hybrid(),
        run_id="daily-round79",
        decision_id="decision-round79",
        symbol_to_security_id={"AAA": "PERM:AAA"},
    )


def _security(symbol: str, canonical_code: str, exchange: str = "XNAS") -> SecurityMaster:
    available = DECISION - timedelta(days=30)
    return SecurityMaster(
        canonical_code=canonical_code,
        symbol=symbol,
        name=symbol,
        market="US",
        exchange=exchange,
        asset_type="etf" if symbol == "SPY" else "stock",
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


def _settings(tmp_path):
    return Settings(
        _env_file=None,
        runtime_profile="FORWARD_SHADOW_VALIDATION",
        llm_provider="deepseek",
        deepseek_api_key="fixture-not-a-secret",
        agentic_shadow_external_enabled=True,
        database_url="sqlite://",
        forward_shadow_lock_path=tmp_path / "shadow.lock",
        forward_outcome_lock_path=tmp_path / "outcome.lock",
    )


def test_real_forward_freeze_contains_five_aligned_variants_and_never_invents_missing_targets(
    session_factory,
) -> None:
    decision = _decision_set()

    assert {item.variant for item in decision.tournament.variants} == set(PortfolioVariant)
    assert {item.symbols for item in decision.tournament.variants} == {("AAA",)}
    assert decision.variant_states[PortfolioVariant.PURE_QUANT] == "SHADOW"
    assert decision.variant_states[PortfolioVariant.QUANT_PLUS_PROBABILITY] == "SHADOW"
    assert decision.variant_states[PortfolioVariant.QUANT_PLUS_LLM] == "SHADOW"
    assert (
        decision.variant_states[PortfolioVariant.QUANT_PLUS_PROBABILITY_PLUS_LLM]
        == "DEGRADED_FALLBACK"
    )
    assert (
        decision.variant_states[PortfolioVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE]
        == "DEGRADED_FALLBACK"
    )

    with session_factory.begin() as session:
        ledger = ForwardCompetitionLedger(session)
        assert ledger.append_decision_set(decision)
        assert not ledger.append_decision_set(decision)
        with pytest.raises(ValueError, match="immutable"):
            ledger.append_decision_set(
                decision.model_copy(update={"data_hash": "rewritten-data"})
            )
        dashboard = competition_dashboard(ledger)
        assert dashboard["frozen_variant_decisions"] == 5
        assert dashboard["promotion_eligible_paired_sets"] == 0


def test_daily_forward_competition_requires_real_origin_and_is_idempotent(session_factory) -> None:
    with session_factory.begin() as session:
        result = append_daily_forward_competition(
            session,
            workflow=_workflow(),
            hybrid_document=_hybrid(),
            evidence=_evidence(),
            run_id="daily-round79",
            decision_id="decision-round79",
            evidence_origin="TEST",
        )
        assert result["reason"] == "NON_REAL_FORWARD_EVIDENCE_ORIGIN"
        assert ForwardCompetitionLedger(session).decision_sets() == ()
        frozen = append_daily_forward_competition(
            session,
            workflow=_workflow(),
            hybrid_document=_hybrid(),
            evidence=_evidence(),
            run_id="daily-round79",
            decision_id="decision-round79",
            evidence_origin="REAL_FORWARD",
        )
        assert frozen["decision_sets"] == 1
        assert frozen["variant_decisions"] == 5
        repeated = append_daily_forward_competition(
            session,
            workflow=_workflow(),
            hybrid_document=_hybrid(),
            evidence=_evidence(),
            run_id="daily-round79",
            decision_id="decision-round79",
            evidence_origin="REAL_FORWARD",
        )
        assert repeated["reason"] == "IDEMPOTENT_REUSE"
        assert len(ForwardCompetitionLedger(session).decision_sets()) == 1


def test_outcome_rejects_future_and_cannot_be_rewritten(session_factory) -> None:
    decision = _decision_set()
    frozen = decision.tournament.variants[0]
    outcome = OutcomeRecord(
        outcome_id="round79-outcome",
        decision_id=frozen.decision_id,
        variant=frozen.variant,
        outcome_time=DECISION + timedelta(days=1),
        evidence_class=EvidenceClass.FORWARD_SHADOW,
        status=OutcomeStatus.COMPLETE,
        realized_return=0.01,
        benchmark_return=0.005,
        excess_return=0.005,
        turnover=0.02,
        expected_cost=0.001,
    )
    record = ForwardCompetitionOutcome(
        competition_id=decision.competition_id,
        decision_set_hash=decision.decision_set_hash,
        evaluation_horizon="1d",
        outcome=outcome,
        data_snapshot_identity={"source": "fixture"},
        source_identity="fixture-source",
        evidence_origin="REAL_FORWARD",
    )
    with session_factory.begin() as session:
        ledger = ForwardCompetitionLedger(session)
        ledger.append_decision_set(decision)
        assert ledger.append_outcome(record)
        assert not ledger.append_outcome(record)
        with pytest.raises(ValueError, match="immutable"):
            ledger.append_outcome(
                record.model_copy(
                    update={
                        "outcome": outcome.model_copy(update={"realized_return": 0.02})
                    }
                )
            )
        with pytest.raises(ValueError, match="future"):
            ledger.append_outcome(
                record.model_copy(
                    update={
                        "evaluation_horizon": "5d",
                        "outcome": outcome.model_copy(
                            update={
                                "outcome_id": "round79-outcome-future",
                                "outcome_time": datetime.now(UTC) + timedelta(minutes=5),
                            }
                        ),
                    }
                )
            )


def test_outcome_collection_waits_for_legal_session_then_appends_each_variant_once(
    session_factory, tmp_path
) -> None:
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
        assert ForwardCompetitionLedger(session).append_decision_set(_decision_set())

    service = ForwardShadowOperations(
        session_factory,
        EffectiveRuntimeConfig(settings=_settings(tmp_path), portfolio_id=None),
        now=lambda: COLLECTED,
    )
    first = service.collect_outcomes(collected_at=COLLECTED)
    second = service.collect_outcomes(collected_at=COLLECTED)

    assert first.competition_outcomes_appended == 5
    assert first.competition_pending_not_matured > 0
    assert second.competition_outcomes_appended == 0
    assert second.competition_duplicate_outcomes == 5
    with session_factory() as session:
        dashboard = competition_dashboard(ForwardCompetitionLedger(session))
        assert dashboard["complete_paired_sets"] == 1
        assert dashboard["promotion_eligible_paired_sets"] == 0
