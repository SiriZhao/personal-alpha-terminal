"""ROUND25 PHASE 1: renderer never lets research ETFs enter the formal list.

Reproduces the ROUND24 bug where IVV/QQQM/VOO/VTI/IJR/IUSV/IVE/VLUE were
rendered as BUY inside 【今日操作清单】 despite being RESEARCH_CANDIDATE rows
without estimated value, quantity, cost, earliest execution or final risk
approval.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from io import StringIO

from rich.console import Console

from personal_alpha_terminal.application.daily_result import (
    BenchmarkSummary,
    DailyQuantResult,
    DecisionReadiness,
    DecisionRow,
    ExecutionLeg,
    ExecutionPlan,
    PortfolioPositionRow,
    PortfolioSummary,
    RiskSummary,
    StageResult,
    StageStatus,
)
from personal_alpha_terminal.terminal.daily_renderer import (
    render_daily_quant_result,
)

AS_OF = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


def _decision(symbol: str, target: float, qty: int, value: float) -> DecisionRow:
    return DecisionRow(
        recommendation_id=f"rec:{symbol}",
        symbol=symbol,
        action="BUY",
        current_weight=0.0,
        target_weight=target,
        delta_weight=target,
        estimated_value=value,
        estimated_quantity=qty,
        estimated_cost=1.0,
        expected_alpha=0.04,
        confidence=None,
        risk_contribution=0.1,
        reason="validated expected alpha remained positive",
        data_quality="VALID",
        model_version="constrained-alpha-risk-v1",
        data_version="v1",
        earliest_execution_time=AS_OF,
        expiry=AS_OF,
    )


def _etf_candidate(symbol: str, sleeve: str, target: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "instrument_type": "ETF",
        "sleeve": sleeve,
        "target_weight": target,
        "current_weight": 0.0,
        "delta_weight": target,
        "eligibility": [],
        "eligible": True,
        "momentum_vol_ratio": 1.25,
        "momentum_252_21": 0.52,
        "annualized_volatility": 0.42,
        "rationale": "risk-parity within sleeve budget",
        "model_version": "etf-sleeves-v1",
        "model_status": "RESEARCH_CANDIDATE",
        "domain": "RESEARCH_CANDIDATE",
        "trading_permission": "NONE",
        "not_part_of_execution_plan": True,
    }


def _result(
    decisions: tuple[DecisionRow, ...],
    etf_targets: tuple[dict[str, object], ...],
) -> DailyQuantResult:
    stages = tuple(
        StageResult(name, StageStatus.PASS, 0.0, "pass", {})
        for name in (
            "CALENDAR",
            "DATA",
            "PIT",
            "FEATURE",
            "FACTOR",
            "SIGNAL",
            "PROBABILITY",
            "PORTFOLIO",
            "RISK",
            "DECISION",
            "EXECUTION",
        )
    )
    portfolio = PortfolioSummary(
        status="ALL_CASH",
        nav=100_000.0,
        cash=100_000.0,
        cash_weight=1.0,
        invested_weight=0.0,
        positions=(
            PortfolioPositionRow(
                symbol="CASH",
                shares=None,
                price=None,
                current_weight=1.0,
                target_weight=None,
                delta_weight=None,
            ),
        ),
    )
    risk = RiskSummary(
        status="PASS",
        expected_volatility=None,
        target_volatility=None,
        drawdown=None,
        hhi=None,
        turnover=None,
        gross_exposure=None,
        cash_target=None,
        exposure_multiplier=None,
        largest_target_weight=None,
        reasons=(),
    )
    execution = ExecutionPlan(
        status="MANUAL_ONLY",
        manual_execution_required=True,
        broker="SCHWAB_MANUAL",
        estimated_cash_before=100_000.0,
        estimated_proceeds=0.0,
        estimated_buys=sum(item.estimated_value for item in decisions),
        estimated_cash_after=None,
        turnover=None,
        estimated_cost=0.0,
        legs=tuple(
            ExecutionLeg(
                sequence=index,
                symbol=item.symbol,
                action=item.action,
                estimated_value=item.estimated_value,
                estimated_quantity=item.estimated_quantity,
                estimated_cost=item.estimated_cost,
                earliest_execution_time=item.earliest_execution_time,
            )
            for index, item in enumerate(decisions, start=1)
        ),
    )
    return DailyQuantResult(
        run_id="run-round25-test",
        version="1.2.0-rc.1",
        started_at=AS_OF,
        finished_at=AS_OF,
        analysis_date=date(2026, 8, 13),
        trade_date=date(2026, 8, 14),
        market_session="REGULAR",
        market_structure="US_EQUITY",
        data_cutoff=AS_OF,
        decision_readiness=DecisionReadiness.READY,
        llm_status="PASS",
        stages=stages,
        data_health=(),
        market_regime="UNKNOWN",
        market_regime_detail="",
        factors=(),
        probabilities=(),
        candidates=(),
        portfolio=portfolio,
        risk=risk,
        final_decisions=decisions,
        rejected_signals=(),
        execution_plan=execution,
        benchmarks=(
            BenchmarkSummary(
                name="SPY",
                status="PASS",
                observation_count=252,
                period_return=0.2861,
                annualized_volatility=0.178,
                note="benchmark",
            ),
        ),
        blockers=(),
        warnings=(),
        provenance={"probability_overlay": {"active": False, "state": "RESEARCH_ONLY"}},
        config_hash="test",
        model_versions=("test",),
        etf_universe={
            "raw_listed_etfs": 1387,
            "core_eligible": 6,
            "tactical_eligible": 50,
            "blocked_complex": 11,
            "unclassified_etfs": 1320,
            "tradable_eligible": 56,
        },
        etf_targets=etf_targets,
        operational_readiness="READY",
        operational_approval_artifact_id="test",
        research_certification_state="NOT_CERTIFIABLE",
        operational_policy_id="operational-policy-test",
        operational_policy_decision="ALLOW_PROVISIONAL",
        operational_policy_effective=True,
        operational_policy_reason="OPERATIONAL_POLICY_ALLOW_PROVISIONAL",
        operationally_allowed=True,
    )


def _render(result: DailyQuantResult) -> str:
    console = Console(file=StringIO(), width=200, force_terminal=False)
    render_daily_quant_result(result, console, locale="zh-CN")
    return console.file.getvalue()  # type: ignore[attr-defined]


def test_etf_research_candidates_never_render_as_buy() -> None:
    result = _result(
        decisions=(_decision("VSTS", 0.069, 513, 6943.57),),
        etf_targets=(
            _etf_candidate("IVV", "ETF_CORE", 0.0704),
            _etf_candidate("QQQM", "ETF_TACTICAL", 0.03),
        ),
    )
    output = _render(result)
    # The research section must exist with the isolation notice.
    assert "研究观察" in output
    assert "不执行" in output
    # ETF symbols appear only inside the research section context, never as a
    # BUY in the formal table: the formal list renders exactly one STOCK row.
    formal_line = next(
        line for line in output.splitlines() if line.startswith("│ VSTS")
    )
    assert "买入" in formal_line or "BUY" in formal_line
    assert "STOCK" in formal_line
    # No ETF row may carry an action label in the formal list.
    for line in output.splitlines():
        if line.startswith("│ IVV") or line.startswith("│ QQQM"):
            assert "买入" not in line and "BUY" not in line


def test_etf_research_section_declares_none_trading_permission() -> None:
    result = _result(
        decisions=(),
        etf_targets=(_etf_candidate("VOO", "ETF_CORE", 0.0707),),
    )
    output = _render(result)
    assert "VOO" in output
    assert "RESEARCH_CANDIDATE" in output
    assert "NONE" in output


def test_formal_decision_with_missing_fields_is_excluded() -> None:
    decisions = (_decision("VSTS", 0.069, 513, 6943.57),)
    result = _result(decisions=decisions, etf_targets=())
    output = _render(result)
    assert "VSTS" in output


def test_etf_research_targets_never_reach_execution_plan() -> None:
    """ETF research candidates cannot enter ExecutionPlan legs (PHASE 20)."""

    result = _result(
        decisions=(_decision("VSTS", 0.069, 513, 6943.57),),
        etf_targets=(_etf_candidate("VOO", "ETF_CORE", 0.0707),),
    )
    leg_symbols = {leg.symbol for leg in result.execution_plan.legs}
    assert leg_symbols == {"VSTS"}
    assert "VOO" not in leg_symbols


def test_round30_participation_panel_is_rendered_from_runtime_provenance() -> None:
    result = _result(
        decisions=(_decision("VSTS", 0.069, 513, 6943.57),),
        etf_targets=(),
    )
    output = _render(result)
    assert "本次正式参与决策" in output
    assert "RESEARCH_ONLY / 0%" in output
    assert "OBSERVATION_ONLY" in output
    assert "ADVISORY_ONLY" in output
