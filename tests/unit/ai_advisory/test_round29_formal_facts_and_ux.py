"""ROUND29 P0/P1: formal facts, company dossiers, news freshness and ETF UX."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from personal_alpha_terminal.ai_advisory.action_commentary import (
    build_deterministic_action_commentaries,
    build_deterministic_devils_advocate,
    build_deterministic_portfolio_review,
    merge_llm_action_commentaries,
    validate_llm_action_commentaries,
)
from personal_alpha_terminal.ai_advisory.facts_v3 import build_facts_v3
from personal_alpha_terminal.ai_advisory.grounding_v3 import (
    GROUNDING_QUARANTINED,
    quarantine_sections,
)
from personal_alpha_terminal.application.daily_result import (
    DailyQuantResult,
    DecisionReadiness,
    ExecutionPlan,
    PortfolioSummary,
    RiskSummary,
)
from personal_alpha_terminal.intelligence.company_dossier import build_company_dossiers
from personal_alpha_terminal.intelligence.market_news import (
    NewsFreshnessBucket,
    NewsItem,
    materialize_news_facts,
)
from personal_alpha_terminal.terminal.daily_renderer import capture_daily_quant_result

sys.path.insert(0, "tests/unit")
import test_terminalization_stage1 as term  # noqa: E402


def _facts_v2() -> dict[str, object]:
    return {
        "run_id": "daily-r29",
        "decision_id": "decision-r29",
        "probability_influence": 0,
        "portfolio": {"total_value": 100_000.0, "cash_balance": 72_772.0},
        "formal_actions": [
            {
                "symbol": "VSTS",
                "action": "BUY",
                "target_weight": 0.0691,
                "expected_alpha": 0.0455,
                "risk_contribution": 0.3295,
                "estimated_cost": 3.93,
                "estimated_value": 6910.0,
                "estimated_quantity": 518,
            }
        ],
        "research_candidates": [],
        "benchmarks": [],
        "factor_count": 3,
        "candidate_count": 1171,
        "factor_statistics": {},
        "risk": {"expected_volatility": 0.076, "gross_exposure": 0.0691},
        "pit_events": [],
        "data_gaps": [],
        "evidence_refs": ["run:daily-r29"],
    }


def test_formal_fact_packet_is_immutable_and_llm_cannot_change_formal_fields() -> None:
    facts = _facts_v2()
    packet = build_facts_v3(facts_v2=facts)
    assert packet["FORMAL_FACT_PACKET"]["immutable"] is True
    assert packet["FORMAL_FACT_PACKET"]["llm_mutable"] is False
    action = packet["FORMAL_ACTIONS"][0]
    assert action["estimated_value"]["value"] == 6910.0
    assert action["estimated_quantity"]["value"] == 518

    base = build_deterministic_action_commentaries(facts=facts)
    llm = [
        {
            "ticker": "VSTS",
            "company_name": "Fake Company",
            "formal_action": "SELL",
            "formal_target_weight": 0.999,
            "llm_view": "SUPPORTIVE",
            "support_level": 80,
            "business_summary": "fake",
            "why_quant_may_like_it": "fake",
            "recent_positive_catalysts": [],
            "recent_negative_catalysts": [],
            "key_risks": [],
            "what_could_make_signal_wrong": "fake",
            "valuation_or_fundamental_context_if_available": "fake",
            "sector_context": "fake",
            "market_context": "fake",
            "earnings_or_filing_context": "fake",
            "event_risk": [],
            "liquidity_comment": "fake",
            "portfolio_role": "fake",
            "correlation_or_overlap_comment": "fake",
            "llm_counterargument": "fake",
            "human_review_focus": "fake",
        }
    ]
    merged = merge_llm_action_commentaries(base=base, llm=llm, facts=facts)
    assert merged[0]["formal_action"] == "BUY"
    assert merged[0]["formal_target_weight"] == 0.0691
    assert validate_llm_action_commentaries(llm, allowed_symbols=frozenset({"VSTS"}))[0] is True
    fake = [dict(llm[0], ticker="NOT_A_FORMAL_TICKER")]
    assert validate_llm_action_commentaries(fake, allowed_symbols=frozenset({"VSTS"}))[0] is False


def test_company_dossier_uses_source_grounding_and_never_fabricates_name() -> None:
    exposure = {
        "market_cap_observations": {
            "VSTS": {
                "market_cap": 1_761_694_189.57,
                "market_cap_calculation": "PROVIDER_REPORTED_MARKET_CAP",
            }
        },
        "sector_acquisition": {"symbol_status": {"VSTS": "SEC_SIC_CURRENT_ONLY"}},
    }

    def fetcher(symbol: str) -> dict[str, object]:
        if symbol == "VSTS":
            return {
                "longName": "Vestis Corporation",
                "sector": "INDUSTRIALS",
                "industry": "Diversified Support Services",
            }
        return {}

    dossiers = build_company_dossiers(
        symbols=("VSTS", "UNKNOWN_TICKER"),
        current_exposure=exposure,
        info_fetcher=fetcher,
    )
    by_symbol = {item.ticker: item for item in dossiers}
    assert by_symbol["VSTS"].company_name == "Vestis Corporation"
    assert by_symbol["VSTS"].market_cap == 1_761_694_189.57
    assert by_symbol["VSTS"].source_evidence["market_cap"] == "PROVIDER_REPORTED_MARKET_CAP"
    assert by_symbol["UNKNOWN_TICKER"].company_name == "UNAVAILABLE"
    assert by_symbol["UNKNOWN_TICKER"].status == "UNAVAILABLE"


def test_news_freshness_buckets_and_historical_context() -> None:
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    cutoff = now - timedelta(days=1)
    items = (
        NewsItem(
            news_id="n1",
            source="BLS",
            source_tier="TIER1_OFFICIAL",
            headline="old BLS",
            summary="old",
            published_at=now - timedelta(days=120),
            retrieved_at=now - timedelta(days=119),
            available_at=cutoff - timedelta(days=119),
            url_hash="u1",
            content_hash="c1",
            topics=("MACRO",),
        ),
        NewsItem(
            news_id="n2",
            source="SEC",
            source_tier="TIER1_OFFICIAL",
            headline="fresh filing",
            summary="fresh",
            published_at=now - timedelta(hours=2),
            retrieved_at=now - timedelta(hours=1),
            available_at=cutoff - timedelta(hours=2),
            url_hash="u2",
            content_hash="c2",
            symbols=("VSTS",),
            topics=("FILING",),
        ),
    )
    result = materialize_news_facts(
        rows=tuple(item.document() for item in items),
        decision_as_of=cutoff,
        formal_symbols=("VSTS",),
        reference_time=now,
    )
    assert result["freshness_counts"][NewsFreshnessBucket.LAST_24H.value] == 1
    assert result["freshness_counts"][NewsFreshnessBucket.HISTORICAL_CONTEXT.value] == 1
    assert result["clusters"][0]["decision_cutoff_relation"] == "PRE_DECISION"
    assert result["clusters"][0]["freshness_bucket"] == "LAST_24H"
    assert result["historical_context"][0]["canonical_headline"] == "old BLS"
    assert result["terminal_displayed_rows"] == 1


def test_ai_commentary_portfolio_review_and_devils_advocate_are_deterministic() -> None:
    facts = _facts_v2()
    commentaries = build_deterministic_action_commentaries(facts=facts)
    assert len(commentaries) == 1
    assert commentaries[0]["formal_action"] == "BUY"
    assert 0 <= commentaries[0]["support_level"] <= 100
    review = build_deterministic_portfolio_review(facts=facts)
    assert review["opinion_status"] == "AI_OPINION_NOT_A_FORMAL_INSTRUCTION"
    devil = build_deterministic_devils_advocate(facts=facts)
    assert devil[0]["ticker"] == "VSTS"
    assert devil[0]["conclusion"] == "未发现可靠反方证据"


def _minimal_result() -> DailyQuantResult:
    return DailyQuantResult(
        run_id="daily-r29",
        version="1.2.0-rc.1",
        started_at=term.NOW,
        finished_at=term.NOW,
        analysis_date=date(2026, 8, 14),
        trade_date=date(2026, 8, 17),
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
        risk=RiskSummary("PASS", 0.08, 0.15, None, 0.01, 0.1, 0.2, 0.8, None, 0.04, ()),
        final_decisions=(),
        rejected_signals=(),
        execution_plan=ExecutionPlan(
            status="READY",
            manual_execution_required=True,
            broker="Charles Schwab",
            estimated_cash_before=100000.0,
            estimated_proceeds=0.0,
            estimated_buys=0.0,
            estimated_cash_after=100000.0,
            turnover=0.0,
            estimated_cost=0.0,
            legs=(),
            execution_plan_generated=True,
            broker_order_submitted=False,
            broker_api="DISABLED",
            execution_mode="MANUAL_ONLY",
        ),
        benchmarks=(),
        blockers=(),
        warnings=(),
        provenance={},
        config_hash="config-r29",
        model_versions=("alpha-v1",),
        etf_targets=(
            {
                "symbol": "VOO",
                "sleeve": "ETF_CORE",
                "target_weight": 0.0707,
                "current_weight": 0.0,
                "momentum_252_21": 0.12,
                "momentum_vol_ratio": 0.9,
                "model_status": "RESEARCH_CANDIDATE",
                "trading_permission": "RESEARCH_ONLY",
                "rationale": "research only",
            },
        ),
    )


def test_etf_research_is_rendered_as_non_actionable() -> None:
    result = replace(_minimal_result(), ai_brief=None)
    rendered = capture_daily_quant_result(result, width=160, locale="zh-CN")
    assert "ETF 正式操作：0" in rendered
    assert "无需执行任何ETF交易" in rendered
    assert "研究观察 · 不需要操作" in rendered
    assert "是否需要操作" in rendered
    assert "交易权限" in rendered


def test_semantic_mismatch_regression_remains_quarantined() -> None:
    facts = _facts_v2()
    packet = build_facts_v3(facts_v2=facts)
    text = "组合总权重约27.23%,现金占比72.77%,前五大持仓合计权重约19.17%。"
    brief = {
        "schema_version": "ai-brief-zh-v2",
        "executive_summary": text,
        "formal_conclusions": text,
        "market_state": text,
        "index_analysis": text,
        "breadth_analysis": text,
        "factor_rotation": text,
        "macro_context": text,
        "important_news": [],
        "sec_events": [],
        "formal_action_explanations": [],
        "etf_research_analysis": [],
        "portfolio_risk_analysis": text,
        "overnight_risk": text,
        "bear_case": text,
        "bull_case": text,
        "uncertainties": [],
        "watchlist_next_sessions": [],
        "data_limitations": [],
        "manual_execution_notes": [],
    }
    merged, report = quarantine_sections(brief, {}, facts_v3=packet)
    assert report["status"] == GROUNDING_QUARANTINED
    assert report["critical_failure"] is True
    assert merged == {}
