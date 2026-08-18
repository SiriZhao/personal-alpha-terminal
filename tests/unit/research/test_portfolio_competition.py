from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from personal_alpha_terminal.research.portfolio_competition import (
    AttributionLayer,
    DecisionFreeze,
    EvidenceClass,
    OutcomeRecord,
    OutcomeStatus,
    PortfolioCompetitionLedger,
    PortfolioVariant,
    PromotionPolicy,
    PromotionVerdict,
    build_tournament,
)

NOW = datetime(2026, 8, 18, 15, tzinfo=UTC)
CUTOFF = NOW - timedelta(minutes=30)


def _freeze(variant: PortfolioVariant, *, decision_id: str = "D1") -> DecisionFreeze:
    return DecisionFreeze(
        decision_id=decision_id,
        decision_time=NOW,
        information_cutoff=CUTOFF,
        variant=variant,
        universe_identity="UNIVERSE-ROUND71",
        symbols=("AAA", "BBB"),
        target_weights={"AAA": 0.30, "BBB": 0.20},
        target_exposure=0.50,
        benchmark="SPY",
        execution_assumptions_hash="exec-v1",
        transaction_cost_model="cost-v1",
        accounting_rules="accounting-v1",
        input_hash="inputs-v1",
        raw_model_output_hash=f"raw-{variant.value}",
        portfolio_recommendation_hash=f"portfolio-{variant.value}",
        risk_adjustments_hash="risk-v1",
        model_versions={"quant": "q-v1", variant.value: "layer-v1"},
        config_hashes={"strategy": "config-v1"},
        reason_codes=("ROUND71_TEST",),
        evidence_class=EvidenceClass.FORWARD_SHADOW,
        frozen_at=NOW,
    )


def _tournament() -> object:
    return build_tournament(
        _freeze(PortfolioVariant.PURE_QUANT),
        _freeze(PortfolioVariant.QUANT_PLUS_PROBABILITY),
        _freeze(PortfolioVariant.QUANT_PLUS_LLM),
        _freeze(PortfolioVariant.QUANT_PLUS_PROBABILITY_PLUS_LLM),
        _freeze(PortfolioVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE),
    )


def _outcome(variant: PortfolioVariant, *, value: float = 0.10) -> OutcomeRecord:
    return OutcomeRecord(
        outcome_id=f"O-{variant.value}",
        decision_id="D1",
        variant=variant,
        outcome_time=NOW + timedelta(days=1),
        evidence_class=EvidenceClass.FORWARD_SHADOW,
        status=OutcomeStatus.COMPLETE,
        realized_return=value,
        benchmark_return=0.05,
        excess_return=value - 0.05,
        upside_capture=1.0,
        downside_capture=0.8,
        max_drawdown=0.10,
        volatility=0.15,
        turnover=0.10,
        expected_cost=0.001,
        risk_adjusted_return=value / 0.15,
        sample_session_count=1,
    )


def test_all_variants_share_identical_frozen_alignment() -> None:
    tournament = _tournament()
    assert len(tournament.variants) == 5
    assert len({item.variant for item in tournament.variants}) == 5
    assert {item.decision_time for item in tournament.variants} == {NOW}
    assert {item.universe_identity for item in tournament.variants} == {"UNIVERSE-ROUND71"}
    assert tournament.tournament_hash


def test_counterfactual_freeze_is_immutable_and_duplicate_ids_are_rejected() -> None:
    ledger = PortfolioCompetitionLedger()
    tournament = _tournament()
    assert ledger.append_tournament(tournament) is True
    assert ledger.append_tournament(tournament) is False

    altered = build_tournament(
        _freeze(PortfolioVariant.PURE_QUANT),
        _freeze(PortfolioVariant.QUANT_PLUS_PROBABILITY),
        _freeze(PortfolioVariant.QUANT_PLUS_LLM),
        _freeze(PortfolioVariant.QUANT_PLUS_PROBABILITY_PLUS_LLM),
        DecisionFreeze(
                **{
                    **_freeze(PortfolioVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE).model_dump(),
                    "target_exposure": 0.90,
                    "freeze_hash": "",
                }
        ),
    )
    with pytest.raises(ValueError, match="cannot be rewritten"):
        ledger.append_tournament(altered)


def test_missing_partial_future_and_duplicate_outcomes_are_fail_closed() -> None:
    ledger = PortfolioCompetitionLedger()
    ledger.append_tournament(_tournament())
    missing = OutcomeRecord(
        outcome_id="O-missing",
        decision_id="D1",
        variant=PortfolioVariant.QUANT_PLUS_LLM,
        outcome_time=NOW + timedelta(days=1),
        evidence_class=EvidenceClass.FORWARD_SHADOW,
        status=OutcomeStatus.MISSING,
    )
    assert ledger.append_outcome(missing) is True
    with pytest.raises(ValueError, match="immutable"):
        ledger.append_outcome(
            OutcomeRecord(
                **{
                    **missing.model_dump(),
                    "outcome_id": "O-missing-rewrite",
                    "status": OutcomeStatus.PARTIAL,
                }
            )
        )
    with pytest.raises(ValueError, match="cannot precede"):
        ledger.append_outcome(
            OutcomeRecord(
                outcome_id="O-future",
                decision_id="D1",
                variant=PortfolioVariant.PURE_QUANT,
                outcome_time=NOW - timedelta(seconds=1),
                evidence_class=EvidenceClass.FORWARD_SHADOW,
                status=OutcomeStatus.MISSING,
            )
        )


def test_restart_replay_and_benchmark_failure_are_preserved() -> None:
    first = PortfolioCompetitionLedger()
    first.append_tournament(_tournament())
    first.append_outcome(
        OutcomeRecord(
            outcome_id="O-partial",
            decision_id="D1",
            variant=PortfolioVariant.PURE_QUANT,
            outcome_time=NOW + timedelta(days=1),
            evidence_class=EvidenceClass.FORWARD_SHADOW,
            status=OutcomeStatus.PARTIAL,
            realized_return=0.02,
            benchmark_available=False,
        )
    )
    replayed = PortfolioCompetitionLedger.from_document(first.replay_document())
    assert replayed.replay_document() == first.replay_document()
    assert replayed.outcomes()[0].benchmark_available is False


def test_insufficient_evidence_does_not_publish_fake_leader() -> None:
    ledger = PortfolioCompetitionLedger()
    ledger.append_tournament(_tournament())
    ledger.append_outcome(_outcome(PortfolioVariant.PURE_QUANT, value=0.10))
    ledger.append_outcome(_outcome(PortfolioVariant.QUANT_PLUS_LLM, value=0.12))
    evaluation = ledger.evaluate(
        evaluated_at=NOW + timedelta(days=2),
        policy=PromotionPolicy(minimum_complete_samples=120, minimum_unique_sessions=40),
    )
    assert evaluation.evidence_accumulating is True
    assert evaluation.strongest_challenger is PortfolioVariant.QUANT_PLUS_LLM
    llm = next(
        item
        for item in evaluation.variant_evaluations
        if item.variant is PortfolioVariant.QUANT_PLUS_LLM
    )
    assert llm.verdict is PromotionVerdict.BLOCKED_INSUFFICIENT_EVIDENCE
    assert evaluation.formal_llm_influence == 0.0
    assert evaluation.formal_probability_influence == 0.0


def test_active_variant_can_be_demoted_when_value_add_deteriorates() -> None:
    ledger = PortfolioCompetitionLedger()
    ledger.append_tournament(_tournament())
    ledger.append_outcome(_outcome(PortfolioVariant.PURE_QUANT, value=0.10))
    ledger.append_outcome(_outcome(PortfolioVariant.QUANT_PLUS_LLM, value=0.08))
    evaluation = ledger.evaluate(
        evaluated_at=NOW + timedelta(days=2),
        policy=PromotionPolicy(
            minimum_complete_samples=1,
            minimum_unique_sessions=1,
            active_variant=PortfolioVariant.QUANT_PLUS_LLM,
        ),
    )
    llm = next(
        item
        for item in evaluation.variant_evaluations
        if item.variant is PortfolioVariant.QUANT_PLUS_LLM
    )
    assert llm.verdict is PromotionVerdict.DEMOTE_TO_SHADOW


def test_attribution_layer_is_explicit() -> None:
    ledger = PortfolioCompetitionLedger()
    ledger.append_tournament(_tournament())
    ledger.append_outcome(_outcome(PortfolioVariant.PURE_QUANT, value=0.10))
    ledger.append_outcome(_outcome(PortfolioVariant.QUANT_PLUS_PROBABILITY, value=0.11))
    evaluation = ledger.evaluate(
        evaluated_at=NOW + timedelta(days=2),
        policy=PromotionPolicy(minimum_complete_samples=1, minimum_unique_sessions=1),
    )
    probability = next(
        item
        for item in evaluation.attribution
        if item.variant is PortfolioVariant.QUANT_PLUS_PROBABILITY
    )
    assert probability.layer is AttributionLayer.PROBABILITY_VALUE_ADD


def test_provider_failure_is_frozen_as_reason_code_without_stale_reuse() -> None:
    failed = DecisionFreeze(
        **{
            **_freeze(PortfolioVariant.QUANT_PLUS_LLM).model_dump(),
            "raw_model_output_hash": "provider-unavailable-no-output",
            "reason_codes": ("LLM_PROVIDER_UNAVAILABLE", "QUANT_ONLY_FALLBACK"),
            "freeze_hash": "",
        }
    )
    tournament = build_tournament(_freeze(PortfolioVariant.PURE_QUANT), failed)
    assert "LLM_PROVIDER_UNAVAILABLE" in tournament.variants[1].reason_codes
    assert tournament.variants[1].raw_model_output_hash == "provider-unavailable-no-output"
