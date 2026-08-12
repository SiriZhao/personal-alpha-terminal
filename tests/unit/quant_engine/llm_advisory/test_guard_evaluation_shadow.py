"""ROUND 9: failure isolation, evaluation, and shadow research tests."""
from __future__ import annotations

import pytest

from personal_alpha_terminal.quant_engine.llm_advisory import (
    LLMGuard,
    LLMGuardStatus,
    ShadowResearchVerdict,
    evaluate_llm,
    evaluate_llm_shadow_research,
)


def _raise_timeout():
    raise TimeoutError("provider timeout")


def _raise_quota():
    from urllib.error import HTTPError

    raise HTTPError("https://x", 429, "quota", None, None)


def _raise_malformed():
    raise ValueError("invalid JSON")


def _ok():
    return "ok"


def test_failure_isolation_timeout_degrades_only_llm() -> None:
    guard = LLMGuard()
    result = guard.run(_raise_timeout, task_name="advisory")
    assert result.status is LLMGuardStatus.DEGRADED
    assert result.quant_impact == "NONE"
    assert result.fallback == "CLASSICAL_CORE_CONTINUES"
    assert any(category == "TIMEOUT" for _name, category in guard.failures)


def test_failure_isolation_quota_and_malformed_json() -> None:
    guard = LLMGuard()
    quota = guard.run(_raise_quota, task_name="advisory")
    assert quota.status is LLMGuardStatus.DEGRADED
    assert any(category == "QUOTA_EXCEEDED" for _n, category in guard.failures)
    malformed = guard.run(_raise_malformed, task_name="advisory")
    assert malformed.status is LLMGuardStatus.DEGRADED
    assert any(category == "MALFORMED_JSON" for _n, category in guard.failures)


def test_failure_isolation_success_returns_ok() -> None:
    guard = LLMGuard()
    result = guard.run(_ok, task_name="advisory")
    assert result.status is LLMGuardStatus.OK
    assert guard.failures == ()


def test_evaluation_passes_when_all_thresholds_met() -> None:
    evaluation = evaluate_llm(
        provider="deepseek",
        model="deepseek-chat",
        grounded=95,
        temporally_correct=98,
        consistent=90,
        schema_valid=97,
        total=100,
        repeated=100,
        latencies_ms=[100, 200, 150],
        total_cost_usd=1.0,
        incremental_quant_value=0.01,
    )
    assert evaluation.pass_thresholds is True
    assert evaluation.hallucination_rate == pytest.approx(0.05)
    assert evaluation.factual_grounding == 0.95
    assert evaluation.mean_latency_ms == pytest.approx(150.0)


def test_evaluation_fails_on_high_hallucination_or_latency() -> None:
    bad_grounding = evaluate_llm(
        provider="deepseek",
        model="deepseek-chat",
        grounded=80,
        temporally_correct=98,
        consistent=90,
        schema_valid=97,
        total=100,
        repeated=100,
        latencies_ms=[100],
        total_cost_usd=1.0,
    )
    assert bad_grounding.pass_thresholds is False
    assert bad_grounding.hallucination_rate == pytest.approx(0.20)
    slow = evaluate_llm(
        provider="deepseek",
        model="deepseek-chat",
        grounded=95,
        temporally_correct=98,
        consistent=90,
        schema_valid=97,
        total=100,
        repeated=100,
        latencies_ms=[15000],
        total_cost_usd=1.0,
    )
    assert slow.pass_thresholds is False


def test_shadow_research_requires_minimum_oos_sample() -> None:
    result = evaluate_llm_shadow_research(
        feature_name="llm_guidance_sentiment",
        classical_oos_net_return=0.01,
        combined_oos_net_return=0.03,
        classical_oos_rank_ic=0.05,
        combined_oos_rank_ic=0.08,
        classical_oos_sharpe=0.6,
        combined_oos_sharpe=0.8,
        sample_size=100,
        min_sample_size=252,
    )
    assert result.verdict is ShadowResearchVerdict.NOT_CERTIFIABLE
    assert "OOS_SAMPLE_INSUFFICIENT" in result.blockers[0]


def test_shadow_research_incremental_value_only_with_real_improvement() -> None:
    good = evaluate_llm_shadow_research(
        feature_name="llm_guidance_sentiment",
        classical_oos_net_return=0.01,
        combined_oos_net_return=0.03,
        classical_oos_rank_ic=0.05,
        combined_oos_rank_ic=0.09,
        classical_oos_sharpe=0.6,
        combined_oos_sharpe=0.8,
        sample_size=300,
    )
    assert good.verdict is ShadowResearchVerdict.INCREMENTAL_VALUE
    no_value = evaluate_llm_shadow_research(
        feature_name="llm_guidance_sentiment",
        classical_oos_net_return=0.01,
        combined_oos_net_return=0.011,  # tiny
        classical_oos_rank_ic=0.05,
        combined_oos_rank_ic=0.052,
        classical_oos_sharpe=0.6,
        combined_oos_sharpe=0.61,
        sample_size=300,
    )
    assert no_value.verdict is ShadowResearchVerdict.NO_INCREMENTAL_VALUE
    assert no_value.blockers == ("NO_INCREMENTAL_VALUE",)


def test_shadow_research_missing_evidence_is_not_certifiable() -> None:
    result = evaluate_llm_shadow_research(
        feature_name="x",
        classical_oos_net_return=None,
        combined_oos_net_return=0.03,
        classical_oos_rank_ic=0.05,
        combined_oos_rank_ic=0.09,
        classical_oos_sharpe=0.6,
        combined_oos_sharpe=0.8,
        sample_size=300,
    )
    assert result.verdict is ShadowResearchVerdict.NOT_CERTIFIABLE
    assert result.blockers == ("OOS_EVIDENCE_INCOMPLETE",)
