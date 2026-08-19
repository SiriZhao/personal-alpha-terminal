from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from personal_alpha_terminal.research.intelligence_tournament import (
    EvidenceDisposition,
    EvidenceProvenance,
    LLMInfluenceLevel,
    LLMResearchEvidence,
    SynchronizedMetricSet,
    TournamentEvidenceClass,
    TournamentEvidenceState,
    TournamentVerdict,
    VariantMeasurement,
    assess_llm_evidence,
    build_controlled_tournament,
    current_tournament_status,
    evaluate_controlled_tournament,
)
from personal_alpha_terminal.research.portfolio_competition import (
    DecisionFreeze,
    EvidenceClass,
    PortfolioVariant,
    TournamentDecision,
)
from personal_alpha_terminal.terminal import cli as terminal_cli

NOW = datetime(2026, 8, 19, 14, tzinfo=UTC)
CUTOFF = NOW - timedelta(minutes=30)


def _freeze(variant: PortfolioVariant) -> DecisionFreeze:
    return DecisionFreeze(
        decision_id="ROUND78-D1",
        decision_time=NOW,
        information_cutoff=CUTOFF,
        variant=variant,
        universe_identity="US-PIT-LOCKED-V1",
        symbols=("AAA", "BBB"),
        target_weights={"AAA": 0.35, "BBB": 0.25},
        target_exposure=0.60,
        benchmark="SPY",
        execution_assumptions_hash="execution-v1",
        transaction_cost_model="cost-v1",
        accounting_rules="accounting-v1",
        input_hash="input-v1",
        raw_model_output_hash=f"raw-{variant.value}",
        portfolio_recommendation_hash=f"portfolio-{variant.value}",
        risk_adjustments_hash="risk-v1",
        model_versions={"quant": "quant-v1", variant.value: "challenger-v1"},
        config_hashes={"strategy": "config-v1"},
        evidence_class=EvidenceClass.HISTORICAL_RESEARCH,
        frozen_at=NOW,
    )


def _tournament() -> TournamentDecision:
    return build_controlled_tournament(*(_freeze(item) for item in PortfolioVariant))


def _evidence(**changes: object) -> TournamentEvidenceState:
    values: dict[str, object] = {
        "data_certification_status": "PASS",
        "locked_oos_status": "PASS",
        "locked_oos_manifest_hash": "sealed-manifest-v1",
        "certified_replay": True,
        "minimum_complete_samples": 3,
        "minimum_unique_sessions": 2,
        "probability_forward_samples": 3,
        "llm_forward_samples": 3,
        "adaptive_exposure_validated": True,
    }
    values.update(changes)
    return TournamentEvidenceState.model_validate(values)


def _metric(
    *,
    after_cost_return: float,
    spy_excess_return: float,
    sharpe: float = 1.0,
    max_drawdown: float = 0.10,
    turnover: float = 0.10,
    cost: float = 0.001,
    recovery_participation: float | None = 1.0,
) -> SynchronizedMetricSet:
    return SynchronizedMetricSet(
        sample_count=3,
        unique_sessions=3,
        after_cost_return=after_cost_return,
        spy_excess_return=spy_excess_return,
        qqq_excess_return=spy_excess_return,
        sharpe=sharpe,
        sortino=sharpe + 0.2,
        max_drawdown=max_drawdown,
        volatility=0.15,
        upside_capture=1.05,
        downside_capture=0.80,
        beta=0.75,
        tracking_error=0.10,
        turnover=turnover,
        cost=cost,
        concentration=0.20,
        average_exposure=0.80,
        recovery_participation=recovery_participation,
        regime_stable=True,
        paired_return_ci=(0.001, 0.030),
    )


def _measurements(*, full_wins: bool = False) -> dict[PortfolioVariant, VariantMeasurement]:
    rows: dict[PortfolioVariant, VariantMeasurement] = {}
    for policy in PortfolioVariant:
        baseline = policy is PortfolioVariant.PURE_QUANT
        winner = full_wins and policy is PortfolioVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE
        rows[policy] = VariantMeasurement(
            policy=policy,
            evidence_class=TournamentEvidenceClass.CERTIFIED_LOCKED_OOS,
            metrics=_metric(
                after_cost_return=0.10 if baseline else (0.12 if winner else 0.09),
                spy_excess_return=0.03 if baseline else (0.05 if winner else 0.02),
                sharpe=0.80 if baseline else (1.00 if winner else 0.70),
                max_drawdown=0.10 if baseline else (0.105 if winner else 0.13),
                turnover=0.10 if baseline else (0.12 if winner else 0.17),
                cost=0.001 if baseline else (0.002 if winner else 0.008),
                recovery_participation=1.10 if winner else 1.00,
            ),
        )
    return rows


def _llm_evidence() -> LLMResearchEvidence:
    return LLMResearchEvidence(
        market={"regime": "trailing-data only"},
        company={"AAA": "filing-based catalyst"},
        portfolio={"risk": "concentration review"},
        provenance=(
            EvidenceProvenance(
                evidence_id="event-1",
                source="immutable-event-corpus",
                observed_at=CUTOFF - timedelta(minutes=2),
                available_at=CUTOFF - timedelta(minutes=1),
                freshness_seconds=3_600,
                confidence=0.80,
                content_hash="event-content-v1",
            ),
        ),
    )


def test_round78_requires_exactly_five_synchronized_policy_freezes() -> None:
    tournament = _tournament()
    assert len(tournament.variants) == 5
    assert tournament.tournament_hash
    with pytest.raises(ValueError, match="exactly the five"):
        build_controlled_tournament(*(_freeze(item) for item in list(PortfolioVariant)[:-1]))
    with pytest.raises(ValueError, match="exactly the five"):
        build_controlled_tournament(*(_freeze(PortfolioVariant.PURE_QUANT) for _ in range(5)))


def test_current_status_blocks_economic_promotion_and_zeroes_formal_influence() -> None:
    evaluation = current_tournament_status(
        data_certification_status="BLOCKED_DATA_QUALITY",
        locked_oos_status="BLOCKED_DATA_QUALITY",
    )

    assert evaluation.production_policy is PortfolioVariant.PURE_QUANT
    assert evaluation.llm_level is LLMInfluenceLevel.L1_SHADOW_SCORING
    assert evaluation.llm_formal_influence == 0
    assert evaluation.probability_formal_influence == 0
    assert "CERTIFIED_DATA_FOUNDATION_REQUIRED" in evaluation.blockers
    assert evaluation.alpha_engine3_attribution.verdict is TournamentVerdict.BLOCKED_DATA_QUALITY
    assert all(
        row.verdict is TournamentVerdict.BLOCKED_DATA_QUALITY
        for row in evaluation.variant_results
    )


def test_malformed_future_and_stale_llm_evidence_fail_soft_to_quant() -> None:
    malformed = assess_llm_evidence({"market": {"regime": 7}}, information_cutoff=CUTOFF)
    future = assess_llm_evidence(
        _llm_evidence().model_copy(
            update={
                "provenance": (
                    _llm_evidence().provenance[0].model_copy(
                        update={"available_at": CUTOFF + timedelta(seconds=1)}
                    ),
                )
            }
        ),
        information_cutoff=CUTOFF,
    )
    stale = assess_llm_evidence(
        _llm_evidence().model_copy(
            update={
                "provenance": (
                    _llm_evidence().provenance[0].model_copy(
                        update={
                            "observed_at": CUTOFF - timedelta(hours=4),
                            "available_at": CUTOFF - timedelta(hours=3),
                        }
                    ),
                )
            }
        ),
        information_cutoff=CUTOFF,
    )

    assert malformed.disposition is EvidenceDisposition.FAIL_SOFT
    assert "LLM_MALFORMED_EVIDENCE" in malformed.reason_codes
    assert "LLM_FUTURE_EVIDENCE" in future.reason_codes
    assert "LLM_STALE_EVIDENCE" in stale.reason_codes
    assert all(item.quant_fallback for item in (malformed, future, stale))


def test_valid_paired_evidence_can_only_promote_when_explicitly_authorized() -> None:
    tournament = _tournament()
    retained = evaluate_controlled_tournament(
        tournament,
        evidence=_evidence(),
        measurements=_measurements(full_wins=True),
        llm_evidence=_llm_evidence(),
    )
    promoted = evaluate_controlled_tournament(
        tournament,
        evidence=_evidence(),
        measurements=_measurements(full_wins=True),
        llm_evidence=_llm_evidence(),
        requested_llm_level=LLMInfluenceLevel.L3_BOUNDED_FORMAL,
        requested_llm_influence=0.10,
        allow_production_promotion=True,
    )

    assert retained.production_policy is PortfolioVariant.PURE_QUANT
    assert retained.llm_formal_influence == 0
    assert promoted.production_policy is PortfolioVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE
    assert promoted.llm_level is LLMInfluenceLevel.L3_BOUNDED_FORMAL
    assert promoted.llm_formal_influence == 0.10
    full = next(
        item
        for item in promoted.variant_results
        if item.policy is PortfolioVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE
    )
    assert full.verdict is TournamentVerdict.PROMOTE


def test_llm_ranking_level_keeps_formal_influence_zero() -> None:
    evaluation = evaluate_controlled_tournament(
        _tournament(),
        evidence=_evidence(),
        measurements=_measurements(full_wins=True),
        llm_evidence=_llm_evidence(),
        requested_llm_level=LLMInfluenceLevel.L2_RANKING,
        requested_llm_influence=0.10,
        allow_production_promotion=True,
    )

    assert evaluation.llm_level is LLMInfluenceLevel.L2_RANKING
    assert evaluation.llm_formal_influence == 0


def test_hard_risk_boundary_overrides_an_apparent_challenger_win() -> None:
    evaluation = evaluate_controlled_tournament(
        _tournament(),
        evidence=_evidence(risk_constraints_authoritative=False),
        measurements=_measurements(full_wins=True),
        llm_evidence=_llm_evidence(),
        requested_llm_level=LLMInfluenceLevel.L3_BOUNDED_FORMAL,
        requested_llm_influence=0.10,
        allow_production_promotion=True,
    )

    assert evaluation.production_policy is PortfolioVariant.PURE_QUANT
    assert evaluation.llm_formal_influence == 0
    assert "HARD_RISK_CONSTRAINTS_REQUIRED" in evaluation.blockers
    full = next(
        item
        for item in evaluation.variant_results
        if item.policy is PortfolioVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE
    )
    assert full.verdict is TournamentVerdict.BLOCKED_INSUFFICIENT_EVIDENCE


def test_active_challenger_is_reversibly_demoted_when_paired_value_deteriorates() -> None:
    evaluation = evaluate_controlled_tournament(
        _tournament(),
        evidence=_evidence(),
        measurements=_measurements(full_wins=False),
        active_challenger=PortfolioVariant.QUANT_PLUS_LLM,
        allow_production_promotion=True,
        llm_evidence=_llm_evidence(),
    )

    assert evaluation.production_policy is PortfolioVariant.PURE_QUANT
    llm = next(
        item
        for item in evaluation.variant_results
        if item.policy is PortfolioVariant.QUANT_PLUS_LLM
    )
    assert llm.verdict is TournamentVerdict.DEMOTE_TO_SHADOW


def test_round78_cli_is_read_only_status_surface() -> None:
    args = terminal_cli.build_parser().parse_args(["intelligence-tournament", "--json"])

    assert args.command == "intelligence-tournament"
    assert args.json is True
