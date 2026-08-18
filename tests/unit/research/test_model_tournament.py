from __future__ import annotations

from dataclasses import replace

from personal_alpha_terminal.research.model_tournament import (
    ComponentAblation,
    FrozenTournamentConfiguration,
    TournamentContender,
    TournamentDiagnostic,
    TournamentEvidenceClass,
    TournamentEvidenceState,
    TournamentMetricSet,
    TournamentVerdict,
    complete_ablation_ledger,
    run_locked_model_tournament,
)


def _configuration() -> FrozenTournamentConfiguration:
    return FrozenTournamentConfiguration(
        universe_id="US_EQUITIES_PIT_V1",
        feature_set_hash="alpha-engine3-feature-set-v1",
        preprocessing_version="alpha-engine3-preprocessing-v1",
        label_horizons=(5, 21, 63),
        model_hyperparameters_hash="round65-hyperparameters-v1",
        llm_provider="deepseek",
        llm_model="deepseek-v4-flash",
        llm_prompt_hash="round63-agentic-prompt-v1",
        probability_model_version="probability-challenger-v1",
        portfolio_constraints_hash="round60-constraints-v1",
        cost_model_version="production-cost-model-v1",
        benchmark_ids=("SPY", "QQQ"),
        rebalance_cadence="MEDIUM_FREQUENCY_EXISTING_POLICY",
        exposure_policy="ROUND64_CHALLENGER_ONLY",
        evaluation_windows=("LOCKED_OOS_PENDING",),
        random_seed=20260818,
    )


def _current_evidence() -> TournamentEvidenceState:
    return TournamentEvidenceState(
        certified_pit_dataset=False,
        historical_membership_coverage=0.0,
        locked_oos_status="NOT_CERTIFIABLE",
        locked_oos_independent_sessions=3,
        probability_forward_observations=0,
        llm_forward_observations=0,
        probability_promotion_approved=False,
        llm_promotion_approved=False,
        adaptive_participation_oos_validated=False,
    )


def _diagnostic(
    contender: TournamentContender,
    evidence_class: TournamentEvidenceClass,
) -> TournamentDiagnostic:
    return TournamentDiagnostic(
        contender=contender,
        evidence_class=evidence_class,
        metrics=TournamentMetricSet(
            total_return=0.10,
            volatility=0.12,
            maximum_drawdown=0.08,
            information_ratio=0.50,
        ),
        eligible_for_promotion=False,
        formal_quant_influence=1.0,
        formal_probability_influence=0.0,
        formal_llm_influence=0.0,
        blockers=("SYNTHETIC_OR_TEST_EVIDENCE_ONLY",),
    )


def test_tournament_configuration_hash_is_deterministic_and_sensitive() -> None:
    first = _configuration()
    second = _configuration()

    assert first.configuration_hash == second.configuration_hash
    assert first.configuration_hash != replace(first, random_seed=1).configuration_hash


def test_current_repository_evidence_blocks_locked_oos_without_promotion() -> None:
    adaptive = _diagnostic(
        TournamentContender.BEST_ADAPTIVE_PARTICIPATION,
        TournamentEvidenceClass.SYNTHETIC_DIAGNOSTIC,
    )
    result = run_locked_model_tournament(
        _configuration(),
        _current_evidence(),
        diagnostics={adaptive.contender: adaptive},
        approved_candidate=adaptive.contender,
    )

    assert result.verdict is TournamentVerdict.BLOCKED_DATA_QUALITY
    assert not result.locked_oos_executed
    assert result.champion is TournamentContender.OLD_PRODUCTION_BASELINE
    assert len(result.diagnostics) == len(TournamentContender)
    assert "CERTIFIED_PIT_DATASET_REQUIRED" in result.blockers
    assert "LOCKED_OOS_NOT_CERTIFIABLE" in result.blockers
    assert all(item.formal_probability_influence == 0 for item in result.diagnostics)
    assert all(item.formal_llm_influence == 0 for item in result.diagnostics)
    retained = next(item for item in result.diagnostics if item.contender is adaptive.contender)
    assert retained.metrics == adaptive.metrics
    assert not retained.eligible_for_promotion


def test_certified_data_without_sufficient_forward_evidence_is_insufficient() -> None:
    evidence = replace(
        _current_evidence(),
        certified_pit_dataset=True,
        historical_membership_coverage=1.0,
        locked_oos_status="CERTIFIED",
    )
    result = run_locked_model_tournament(_configuration(), evidence)

    assert result.verdict is TournamentVerdict.INSUFFICIENT_EVIDENCE
    assert "LOCKED_OOS_SAMPLE_INSUFFICIENT" in result.blockers
    assert "LLM_FORWARD_EVIDENCE_INSUFFICIENT" in result.blockers


def test_only_locked_oos_candidate_can_be_promoted() -> None:
    evidence = TournamentEvidenceState(
        certified_pit_dataset=True,
        historical_membership_coverage=1.0,
        locked_oos_status="CERTIFIED",
        locked_oos_independent_sessions=40,
        probability_forward_observations=40,
        llm_forward_observations=40,
        probability_promotion_approved=True,
        llm_promotion_approved=True,
        adaptive_participation_oos_validated=True,
    )
    candidate = _diagnostic(
        TournamentContender.ALPHA_ENGINE3_QUANT_ONLY,
        TournamentEvidenceClass.LOCKED_OOS,
    )
    candidate = replace(candidate, blockers=())
    promoted = run_locked_model_tournament(
        _configuration(),
        evidence,
        diagnostics={candidate.contender: candidate},
        approved_candidate=candidate.contender,
    )
    synthetic = replace(
        candidate,
        evidence_class=TournamentEvidenceClass.SYNTHETIC_DIAGNOSTIC,
        blockers=("SYNTHETIC_ONLY",),
    )
    rejected = run_locked_model_tournament(
        _configuration(),
        evidence,
        diagnostics={synthetic.contender: synthetic},
        approved_candidate=synthetic.contender,
    )

    assert promoted.verdict is TournamentVerdict.PROMOTE_NEW_CHAMPION
    assert promoted.champion is candidate.contender
    assert rejected.verdict is TournamentVerdict.KEEP_EXISTING_CHAMPION


def test_ablation_ledger_is_complete_without_fabricating_missing_values() -> None:
    momentum = ComponentAblation(
        component="momentum",
        evidence_class=TournamentEvidenceClass.SYNTHETIC_DIAGNOSTIC,
        marginal_net_return=0.0645,
        marginal_information_ratio=None,
        blockers=("SYNTHETIC_ONLY",),
    )
    ledger = complete_ablation_ledger({"momentum": momentum})

    assert len(ledger) == 9
    assert ledger[0] == momentum
    assert all(
        item.blockers
        for item in ledger
        if item.evidence_class is TournamentEvidenceClass.UNAVAILABLE
    )
