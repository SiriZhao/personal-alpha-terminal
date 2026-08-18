from __future__ import annotations

from personal_alpha_terminal.research.forward_shadow_readiness import (
    ReadinessState,
    evaluate_forward_shadow_readiness,
)


def _dashboard(sample: int = 0) -> dict[str, object]:
    return {
        "authority": {
            "execution": "MANUAL_CONFIRMATION",
            "production_lambda": 0.0,
        },
        "forward_evidence": {"valid_paired_observations": sample},
        "promotion_evidence": {
            "status": "NO_FORWARD_EVIDENCE" if sample == 0 else "ELIGIBLE_FOR_PROMOTION_REVIEW",
            "promotion_reason": "INSUFFICIENT_SAMPLE" if sample == 0 else "PASS",
        },
        "provider_health": {"connectivity": "NOT_TESTED"},
    }


def test_data_or_terminal_failure_is_not_ready() -> None:
    readiness = evaluate_forward_shadow_readiness(
        _dashboard(),
        terminal_startup=True,
        terminal_full_cycle=False,
        data_quality_status="BLOCKED_DATA_QUALITY",
    )
    assert readiness.state is ReadinessState.NOT_READY
    assert "DATA_PIT_OR_SURVIVORSHIP_GATE" in readiness.blockers
    assert "TERMINAL_FULL_CYCLE" in readiness.blockers


def test_forward_shadow_ready_does_not_require_fake_alpha_confidence() -> None:
    readiness = evaluate_forward_shadow_readiness(
        _dashboard(sample=10),
        terminal_startup=True,
        terminal_full_cycle=True,
        data_quality_status="PASS_WITH_WARNINGS",
    )
    assert readiness.state is ReadinessState.FORWARD_SHADOW_READY
    assert readiness.forward_sample_size == 10
    assert readiness.production_llm_influence == 0.0


def test_paper_ready_requires_real_sample_and_cycle() -> None:
    readiness = evaluate_forward_shadow_readiness(
        _dashboard(sample=120),
        terminal_startup=True,
        terminal_full_cycle=True,
        data_quality_status="PASS",
    )
    assert readiness.state is ReadinessState.PAPER_READY
    assert readiness.blockers == ()
