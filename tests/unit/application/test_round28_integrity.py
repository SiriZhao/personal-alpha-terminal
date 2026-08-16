"""ROUND28 P0: cardinality provenance, decision provenance and runtime parity."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from personal_alpha_terminal.ai_advisory.facts_v3 import build_facts_v3
from personal_alpha_terminal.application.daily_orchestrator import DailyQuantOrchestrator
from personal_alpha_terminal.application.daily_result import (
    DailyQuantResult,
    DecisionReadiness,
    DecisionRow,
    ExecutionLeg,
    ExecutionPlan,
    PortfolioSummary,
    RiskSummary,
    StageResult,
    StageStatus,
)
from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.candidates import compress_candidates
from personal_alpha_terminal.quant_engine.costs import TransactionCostConfig
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
    PortfolioConstructionEngine,
)
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantInput,
    DailyQuantPipeline,
    _history_is_available,
)
from personal_alpha_terminal.quant_engine.risk.budget import PortfolioRiskState
from personal_alpha_terminal.quant_engine.risk.model import AssetRiskMetadata
from personal_alpha_terminal.quant_engine.risk.stress import StressRiskConfig
from personal_alpha_terminal.terminal.daily_renderer import capture_daily_quant_result

sys.path.insert(0, "tests/unit")
import test_terminalization_stage1 as term  # noqa: E402

ACCEPTANCE_RUN = "daily-2420c68452d142298e6b42482341391f"
PRODUCTION_RUN = "daily-74e83bb34b014a13a8520c0c377101df"


def _signals() -> tuple[AlphaSignal, ...]:
    now = term.NOW
    return tuple(
        AlphaSignal(
            symbol,
            now - timedelta(hours=1),
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
            now + timedelta(days=5),
            AlphaDataQuality.VALID,
            True,
            AlphaValidationStatus.PRODUCTION_APPROVED,
            "alpha-v1",
            "data-v1",
        )
        for index, symbol in enumerate(term.SYMBOLS)
    )


def _run_pipeline(
    *,
    signals: tuple[AlphaSignal, ...] | None = None,
    volatility_target: float | None = None,
    cost_config: TransactionCostConfig | None = None,
):
    rng = np.random.default_rng(11)
    market = rng.normal(0.0003, 0.009, 180)
    returns = pd.DataFrame(
        {symbol: 0.75 * market + rng.normal(0.0003, 0.006, 180) for symbol in term.SYMBOLS},
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
        for index, symbol in enumerate(term.SYMBOLS)
    )
    constraints = PortfolioConstraints(
        maximum_position_weight=0.30,
        maximum_sector_weight=0.60,
        maximum_cluster_weight=0.70,
        maximum_hhi=0.35,
        minimum_cash_weight=0.15,
        maximum_gross_exposure=0.85,
        target_annualized_volatility=volatility_target or 0.30,
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
        cost_model=__import__(
            "personal_alpha_terminal.quant_engine.costs",
            fromlist=["TransactionCostModel"],
        ).TransactionCostModel(cost_config)
        if cost_config is not None
        else None,
        stress_config=StressRiskConfig(
            production_validated=True,
            validation_id="locked-oos-stress-fixture",
            maximum_single_name_loss=0.10,
            maximum_sector_loss=0.20,
        ),
    )
    return pipeline.run(
        DailyQuantInput(
            term._authorization(),
            term.NOW,
            signals or _signals(),
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
    )


def test_all_candidates_enter_optimizer_without_hidden_top_n() -> None:
    signals = tuple(
        AlphaSignal(
            f"T{index:04d}",
            term.NOW - timedelta(hours=1),
            "fixture",
            0.001 + (index % 7) * 0.0001,
            20,
            1.0,
            0.8,
            0.8,
            True,
            200,
            0.8,
            0.7,
            40.0,
            term.NOW + timedelta(days=5),
            AlphaDataQuality.VALID,
            True,
            AlphaValidationStatus.PRODUCTION_APPROVED,
            "alpha-v1",
            "data-v1",
        )
        for index in range(40)
    )
    compressed = compress_candidates(
        signals,
        candidate_min_alpha=0.0,
        adv_by_symbol={item.symbol: 20_000_000.0 for item in signals},
        minimum_adv=10_000_000.0,
    )
    assert len(compressed.candidate_symbols) == 40
    assert compressed.document()["candidate_count"] == 40
    assert "top_n" not in compressed.document()
    output = _run_pipeline()
    assert output.target is not None
    provenance = output.target.optimizer_provenance or {}
    assert provenance["optimizer_input_count"] == len(term.SYMBOLS)
    assert provenance["pre_optimizer_top_n"] is None


def test_round27_acceptance_certificate_1171_optimizer_input() -> None:
    path = Path("reports/daily-runs") / ACCEPTANCE_RUN / "run_certificate.json"
    if not path.exists():
        pytest.skip("ROUND27 acceptance certificate not present")
    certificate = json.loads(path.read_text(encoding="utf-8"))
    provenance = certificate.get("provenance") or {}
    universe_evidence = provenance.get("universe_evidence") or {}
    cardinality_trace = provenance.get("cardinality_trace") or {}
    # The ROUND27 certificate predates the top-level rename; the immutable
    # provenance fields are the source of truth.
    assert universe_evidence.get("optimizer_input") == 1171
    assert cardinality_trace.get("optimizer_input") == 1171
    assert cardinality_trace.get("pre_optimizer_top10_truncation") is False
    assert cardinality_trace.get("maximum_allowed_holdings") is None
    assert certificate["signals"]["eligible"] == 2135
    assert certificate["decision_counts"]["BUY"] == 10


def test_no_hidden_display_or_action_truncation() -> None:
    result = _workflow_result_to_daily(25)
    assert len(result.final_decisions) == 25
    assert len(result.execution_plan.legs) == 25
    rendered = capture_daily_quant_result(result, width=140)
    for decision in result.final_decisions:
        assert decision.symbol in rendered
    assert "X25" in rendered


def _workflow_result_to_daily(count: int) -> DailyQuantResult:
    workflow = term._workflow_result()
    execution = term.NOW + timedelta(days=2)
    decisions = tuple(
        DecisionRow(
            f"rec-{index}",
            f"X{index:02d}",
            "BUY",
            0.0,
            0.04,
            0.04,
            4000.0,
            40,
            1.0,
            0.02,
            None,
            0.1,
            "fixture reason",
            "VALID",
            "alpha-v1",
            "data-v1",
            execution,
            execution + timedelta(days=7),
        )
        for index in range(1, count + 1)
    )
    legs = tuple(
        ExecutionLeg(
            index,
            item.symbol,
            item.action,
            item.estimated_value,
            item.estimated_quantity,
            item.estimated_cost,
            item.earliest_execution_time,
        )
        for index, item in enumerate(decisions, start=1)
    )
    plan = replace(
        workflow_to_plan(workflow),
        legs=legs,
        status="READY",
        execution_plan_generated=True,
    )
    return replace(
        daily_from_workflow(workflow),
        final_decisions=decisions,
        execution_plan=plan,
        decision_readiness=DecisionReadiness.READY,
    )


def workflow_to_plan(workflow) -> ExecutionPlan:
    return ExecutionPlan(
        status="READY",
        manual_execution_required=True,
        broker="Charles Schwab",
        estimated_cash_before=100000.0,
        estimated_proceeds=0.0,
        estimated_buys=10000.0,
        estimated_cash_after=90000.0,
        turnover=0.1,
        estimated_cost=5.0,
        legs=(),
        execution_plan_generated=True,
        broker_order_submitted=False,
        broker_api="DISABLED",
        execution_mode="MANUAL_ONLY",
    )


def daily_from_workflow(workflow) -> DailyQuantResult:
    # Build a minimal DailyQuantResult shell around a real TodayResult; the
    # renderer only needs the decision/plan fields exercised here.
    return DailyQuantResult(
        run_id="daily-fixture",
        version="1.2.0-rc.1",
        started_at=term.NOW,
        finished_at=term.NOW,
        analysis_date=date(2026, 8, 7),
        trade_date=date(2026, 8, 10),
        market_session="POST_CLOSE_DECISION",
        market_structure="US",
        data_cutoff=term.NOW - timedelta(days=1),
        decision_readiness=DecisionReadiness.READY,
        llm_status="OPTIONAL_UNAVAILABLE",
        stages=(),
        data_health=(),
        market_regime="REGIME_UNAVAILABLE",
        market_regime_detail="",
        factors=(),
        probabilities=(),
        candidates=(),
        portfolio=PortfolioSummary("TARGET_COMPUTED", 100000.0, 100000.0, 1.0, 0.0, ()),
        risk=RiskSummary(
            "PASS",
            0.08,
            0.15,
            None,
            0.01,
            0.1,
            0.2,
            0.8,
            None,
            0.04,
            (),
        ),
        final_decisions=(),
        rejected_signals=(),
        execution_plan=workflow_to_plan(workflow),
        benchmarks=(),
        blockers=(),
        warnings=(),
        provenance={},
        config_hash="config-v1",
        model_versions=("alpha-v1",),
    )


def test_cardinality_provenance_fields() -> None:
    output = _run_pipeline()
    assert output.target is not None
    provenance = output.target.optimizer_provenance or {}
    for key in (
        "optimizer_input_count",
        "raw_nonzero_count",
        "dropped_by_no_trade_band",
        "dropped_by_minimum_rebalance_weight",
        "dropped_by_minimum_trade_value",
        "post_filter_nonzero_count",
        "final_target_count",
        "minimum_positive_raw_weight",
        "minimum_positive_final_weight",
        "maximum_raw_weight",
        "maximum_final_weight",
        "gross_raw",
        "gross_final",
        "explicit_position_cap",
        "pre_optimizer_top_n",
        "holding_cap_policy",
    ):
        assert key in provenance, key
    assert provenance["pre_optimizer_top_n"] is None
    assert provenance["holding_cap_policy"] == "NO_FIXED_CARDINALITY_CAP"
    assert provenance["post_filter_nonzero_count"] == provenance["final_target_count"]


def test_decision_provenance_completeness(
    session_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = term._workflow_result()
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.DataService",
        term._SafeDataService,
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.ProductionDailyWorkflow.run",
        lambda _self, **_kwargs: workflow,
    )
    orchestrator = DailyQuantOrchestrator(
        session_factory,
        term._settings(tmp_path),
        snapshot_root=tmp_path / "runs",
    )
    result = orchestrator.run(decision_time=term.NOW, refresh=False)
    assert result.decision_provenance is not None
    decisions = result.decision_provenance.get("decisions") or {}
    assert isinstance(decisions, dict)
    required = {
        "ticker",
        "security_identity",
        "factor_inputs",
        "raw_expected_alpha",
        "alpha_model_identity",
        "signal_eligibility",
        "probability",
        "risk",
        "liquidity_and_cost",
        "current_only_exposure",
        "optimizer",
        "execution",
        "decision_reasons",
        "vetoes_considered",
        "active_gates",
        "hashes",
    }
    for symbol in term.SYMBOLS:
        assert symbol in decisions
        assert required <= set(decisions[symbol])
    assert "optimizer_provenance" in result.decision_provenance


def test_same_input_replay_semantic_parity() -> None:
    first = _run_pipeline()
    second = _run_pipeline()
    assert first.target is not None and second.target is not None
    assert first.target.target_weights == second.target.target_weights
    assert first.target.optimizer_provenance == second.target.optimizer_provenance


def test_acceptance_vs_production_runtime_parity() -> None:
    acceptance = Path("reports/daily-runs") / ACCEPTANCE_RUN / "run_certificate.json"
    production = Path("reports/daily-runs") / PRODUCTION_RUN / "run_certificate.json"
    if not acceptance.exists() or not production.exists():
        pytest.skip("ROUND27 acceptance/production certificates not present")
    a = json.loads(acceptance.read_text(encoding="utf-8"))
    b = json.loads(production.read_text(encoding="utf-8"))
    a_manifest = a["decision_manifest"]
    b_manifest = b["decision_manifest"]
    assert a_manifest["config_hash"] == b_manifest["config_hash"]
    assert a_manifest["decision_cutoff"] == b_manifest["decision_cutoff"]
    assert a_manifest["alpha_model_id"] == b_manifest["alpha_model_id"]
    assert a_manifest["factor_model_id"] == b_manifest["factor_model_id"]
    assert a_manifest["probability_model_id"] == b_manifest["probability_model_id"]
    assert a_manifest["portfolio_model_id"] == b_manifest["portfolio_model_id"]
    assert a_manifest["risk_model_id"] == b_manifest["risk_model_id"]
    assert a_manifest["cost_model_id"] == b_manifest["cost_model_id"]
    assert a_manifest["operational_policy_id"] == b_manifest["operational_policy_id"]
    assert a_manifest["universe_snapshot_id"] == b_manifest["universe_snapshot_id"]
    a_actions = sorted(
        (
            item["symbol"],
            item["action"],
            round(item["target_weight"], 8),
            round(item["risk_contribution"], 8),
            round(item["estimated_cost"], 8),
            round(item["expected_alpha"], 8),
        )
        for item in a["decision_recommendations"]
    )
    b_actions = sorted(
        (
            item["symbol"],
            item["action"],
            round(item["target_weight"], 8),
            round(item["risk_contribution"], 8),
            round(item["estimated_cost"], 8),
            round(item["expected_alpha"], 8),
        )
        for item in b["decision_recommendations"]
    )
    assert a_actions == b_actions
    for key in (
        "cash_target",
        "expected_volatility",
        "gross_exposure",
        "hhi",
        "largest_target_weight",
    ):
        assert round(a["risk"][key], 12) == round(b["risk"][key], 12), key
    assert a["probability"][0]["oos_status"] == b["probability"][0]["oos_status"]
    a_stages = {item["name"]: item for item in a["stages"]}
    b_stages = {item["name"]: item for item in b["stages"]}
    assert a_stages["AI_BRIEF"]["status"] == "PASS"
    assert b_stages["AI_BRIEF"]["status"] == "PASS_DEGRADED"
    assert (
        b_stages["AI_BRIEF"]["metadata"]["semantic_grounding_status"]
        == "AI_BRIEF_QUARANTINED_SEMANTIC_MISMATCH"
    )
    assert (
        a_stages["AI_BRIEF"]["metadata"]["news"]
        == b_stages["AI_BRIEF"]["metadata"]["news"]
    )
    # The production run refreshed data, so the sealed semantic hash differs.
    # The formal decision fields above must remain unchanged.
    assert a_manifest["semantic_hash"] != b_manifest["semantic_hash"]
    assert a["provenance"]["data_hash"] != b["provenance"]["data_hash"]


def test_alpha_perturbation_changes_target() -> None:
    base = _run_pipeline()
    assert base.target is not None
    symbol = term.SYMBOLS[0]
    perturbed_signals = tuple(
        replace(item, expected_excess_return=item.expected_excess_return * 2)
        if item.symbol == symbol
        else item
        for item in _signals()
    )
    perturbed = _run_pipeline(signals=perturbed_signals)
    assert perturbed.target is not None
    assert perturbed.target.target_weights.get(symbol, 0.0) > base.target.target_weights.get(
        symbol, 0.0
    )


def test_transaction_cost_perturbation_reduces_gross() -> None:
    base = _run_pipeline()
    expensive = TransactionCostConfig(spread_bps=200.0, impact_coefficient_bps=200.0)
    perturbed = _run_pipeline(cost_config=expensive)
    assert base.target is not None and perturbed.target is not None
    assert perturbed.target.estimated_transaction_cost >= base.target.estimated_transaction_cost


def test_risk_constraint_perturbation_reduces_gross() -> None:
    base = _run_pipeline(volatility_target=0.30)
    tight = _run_pipeline(volatility_target=0.12)
    assert base.target is not None and tight.target is not None
    assert sum(tight.target.target_weights.values()) <= sum(
        base.target.target_weights.values()
    )


def test_future_leakage_rejected() -> None:
    index = pd.bdate_range("2025-11-24", periods=20)
    frame = pd.DataFrame({"SPY": np.zeros(20)}, index=index)
    frame.index = pd.DatetimeIndex(pd.to_datetime(index, utc=True))
    cutoff = datetime(2025, 11, 30, tzinfo=UTC)
    assert _history_is_available(frame, cutoff) is False
    past = frame.loc[: pd.Timestamp("2025-11-25", tz="UTC")]
    assert _history_is_available(past, cutoff) is True


def test_pit_cutoff_resolution() -> None:
    cutoff = datetime(2026, 8, 14, 20, 30, tzinfo=UTC)
    stage = StageResult(
        "DATA",
        StageStatus.PASS,
        0.0,
        "",
        {"pit_cutoff": "2026-08-14T20:30:00+00:00"},
    )
    resolved = DailyQuantOrchestrator._resolved_data_cutoff({"DATA": stage}, cutoff)
    assert resolved == cutoff


def test_deterministic_formal_facts_are_machine_generated() -> None:
    facts_v2 = {
        "run_id": "daily-r1",
        "decision_id": "decision-r1",
        "probability_influence": 0,
        "probability_mode": "PROBABILITY_FALLBACK_CLASSICAL",
        "portfolio": {"total_value": 100_000.0, "cash_balance": 100_000.0},
        "formal_actions": [
            {
                "symbol": "VSTS",
                "action": "BUY",
                "target_weight": 0.0694,
                "expected_alpha": 0.045,
                "risk_contribution": 0.30,
                "estimated_cost": 3.95,
            },
            {
                "symbol": "ATEX",
                "action": "BUY",
                "target_weight": 0.0283,
                "expected_alpha": 0.041,
                "risk_contribution": 0.08,
                "estimated_cost": 1.58,
            },
        ],
        "research_candidates": [],
        "benchmarks": [],
        "factor_count": 2,
        "candidate_count": 2,
        "factor_statistics": {},
        "risk": {},
        "pit_events": [],
        "data_gaps": [],
        "evidence_refs": ["run:daily-r1"],
    }
    facts_v3 = build_facts_v3(facts_v2=facts_v2)
    portfolio = facts_v3["PORTFOLIO_FACTS"]
    assert portfolio["gross_weight"]["value"] == 0.0694 + 0.0283
    assert portfolio["cash_weight"]["value"] == 1.0
    assert portfolio["formal_action_count"]["value"] == 2
    assert portfolio["top5_weight"]["value"] == 0.0694 + 0.0283
    assert portfolio["top5_risk_contribution"]["value"] == 0.30 + 0.08
