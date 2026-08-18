from __future__ import annotations

from datetime import UTC, datetime, timedelta

from personal_alpha_terminal.intelligence.llm_decision_fusion import (
    DecisionInfluenceLevel,
    DisagreementCategory,
    EvidenceProvenance,
    EvidenceState,
    bounded_fusion,
    classify_disagreement,
    parse_structured_decision,
    resolve_influence_level,
)

NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)


def _evidence(
    *,
    available_at: datetime = NOW - timedelta(hours=1),
    state: str = "VERIFIED",
) -> dict[str, object]:
    return {
        "source_id": "wire-1",
        "source_type": "SEC_FILING",
        "observed_at": available_at - timedelta(minutes=5),
        "available_at": available_at,
        "freshness": 0.9,
        "confidence": 0.8,
        "state": state,
        "evidence_ids": ["event-1"],
    }


def _payload() -> dict[str, object]:
    evidence = _evidence()
    return {
        "decision_timestamp": NOW.isoformat(),
        "information_cutoff": (NOW - timedelta(minutes=30)).isoformat(),
        "market": {
            "market_regime_view": "NORMAL",
            "regime_confidence": 0.8,
            "risk_budget_adjustment": 0.0,
            "exposure_adjustment": 0.1,
            "breadth_trend_interpretation": "Breadth is constructive.",
            "uncertainty": 0.2,
            "evidence": [evidence],
        },
        "candidates": [
            {
                "symbol": "AAA",
                "company_summary": "Industrial software company.",
                "business_quality_view": "Stable recurring revenue.",
                "recent_developments": ["Product launch"],
                "catalysts": ["Demand growth"],
                "risks": ["Execution"],
                "event_risk": [],
                "conviction": 0.4,
                "quant_disagreement": 0.2,
                "ranking_adjustment": 0.2,
                "position_conviction_adjustment": 0.1,
                "action_urgency": 0.4,
                "reasoning": "Evidence-backed review.",
                "evidence": [evidence],
            }
        ],
        "portfolio": {
            "portfolio_view": "Remain diversified.",
            "risk_budget_adjustment": 0.0,
            "target_exposure_adjustment": 0.05,
            "rebalance_urgency": 0.2,
            "reasoning": "No hard-risk override.",
            "evidence": [evidence],
        },
        "overall_confidence": 0.8,
        "uncertainty": 0.2,
        "evidence_summary": "All claims cite supplied evidence.",
    }


def test_malformed_output_fails_soft_without_reusing_stale_result() -> None:
    outcome = parse_structured_decision(
        {"market": "not-an-object"},
        allowed_symbols=frozenset({"AAA"}),
        information_cutoff=NOW,
    )
    assert outcome.degraded is True
    assert outcome.decision is None
    assert outcome.error


def test_future_or_conflicting_evidence_is_rejected_or_classified() -> None:
    payload = _payload()
    market = payload["market"]
    assert isinstance(market, dict)
    market["evidence"] = [_evidence(available_at=NOW + timedelta(minutes=1))]
    outcome = parse_structured_decision(
        payload,
        allowed_symbols=frozenset({"AAA"}),
        information_cutoff=NOW,
    )
    assert outcome.degraded is True

    disagreement = classify_disagreement(
        symbol="AAA",
        quant_view=0.2,
        llm_view=0.9,
        evidence_state=EvidenceState.CONFLICTING,
    )
    assert disagreement.category is DisagreementCategory.EVENT_CONFLICT
    assert disagreement.fusion_result == "BOUNDED_REVIEW"


def test_influence_ladder_stays_shadow_until_evidence_and_promotion_pass() -> None:
    assert (
        resolve_influence_level(
            DecisionInfluenceLevel.L4_ADAPTIVE_EVIDENCE,
            promotion_passed=False,
            evidence_verified=True,
            production_enabled=True,
        )
        is DecisionInfluenceLevel.L1_SHADOW_SCORING
    )
    assert (
        resolve_influence_level(
            DecisionInfluenceLevel.L4_ADAPTIVE_EVIDENCE,
            promotion_passed=True,
            evidence_verified=True,
            production_enabled=False,
        )
        is DecisionInfluenceLevel.L1_SHADOW_SCORING
    )


def test_extreme_adjustments_are_bounded_and_hard_risk_wins() -> None:
    bounded = bounded_fusion(
        {"AAA": 0.1, "BBB": -0.1},
        {"AAA": 99.0, "BBB": -99.0},
        influence=0.5,
        max_adjustment=0.2,
        hard_constraints_ok=True,
    )
    assert bounded.fused_scores == {"AAA": 0.2, "BBB": -0.2}
    assert bounded.hard_risk_overridden is False

    overridden = bounded_fusion(
        {"AAA": 0.1},
        {"AAA": 0.2},
        influence=1.0,
        max_adjustment=0.2,
        hard_constraints_ok=False,
    )
    assert overridden.fused_scores == {"AAA": 0.1}
    assert overridden.applied_influence == 0.0
    assert overridden.hard_risk_overridden is True


def test_provenance_contract_requires_aware_timestamps() -> None:
    try:
        EvidenceProvenance(
            source_id="x",
            source_type="NEWS",
            observed_at=datetime(2026, 8, 18, 10),
            available_at=NOW,
            freshness=0.5,
            confidence=0.5,
            state=EvidenceState.UNKNOWN_UNVERIFIED,
        )
    except ValueError as error:
        assert "timezone-aware" in str(error)
    else:
        raise AssertionError("naive provenance timestamps must be rejected")
