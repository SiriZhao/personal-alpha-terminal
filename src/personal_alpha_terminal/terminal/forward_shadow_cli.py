"""Operator CLI for real Forward Shadow validation operations."""

from __future__ import annotations

import json
from argparse import Namespace
from datetime import datetime

from rich.console import Console
from rich.table import Table

from personal_alpha_terminal.application.forward_shadow_operations import (
    ForwardShadowExitCode,
    ForwardShadowOperations,
    ForwardShadowRunResult,
    probe_forward_shadow_provider,
)
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.data.database import configure_database, get_session_factory
from personal_alpha_terminal.data.migrations import upgrade_database
from personal_alpha_terminal.terminal.daily_renderer import render_daily_quant_result

console = Console()


def forward_shadow_command(args: Namespace, config: EffectiveRuntimeConfig) -> int:
    action = str(args.forward_shadow_action)
    if action == "provider-status":
        health = probe_forward_shadow_provider(config.settings, live=False)
        console.print(json.dumps(health.document(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if action == "provider-test":
        health = probe_forward_shadow_provider(config.settings, live=bool(args.live))
        console.print(json.dumps(health.document(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if health.connectivity == "AVAILABLE" else int(
            ForwardShadowExitCode.CONFIG_ERROR
            if health.connectivity == "CONFIG_ERROR"
            else ForwardShadowExitCode.RETRYABLE_PROVIDER_FAILURE
        )
    _prepare(config)
    service = ForwardShadowOperations(get_session_factory(), config)
    if action == "run":
        return _run(
            service,
            decision_time=_optional_datetime(args.decision_time),
            refresh=not bool(args.no_refresh),
        )
    if action == "resume":
        resumed = service.resume(
            shadow_run_id=args.run_id,
            refresh=bool(args.refresh),
        )
        if resumed is None:
            console.print("没有可恢复的 Forward Shadow run。")
            return 0
        render_daily_quant_result(resumed.result, console)
        _render_daily_summary(resumed)
        return int(resumed.exit_code)
    if action == "collect-outcomes":
        result = service.collect_outcomes(collected_at=_optional_datetime(args.as_of))
        console.print(
            json.dumps(
                {
                    "scanned_predictions": result.scanned_predictions,
                    "matured_pairs": result.matured_pairs,
                    "outcomes_appended": result.outcomes_appended,
                    "pending_not_matured": result.pending_not_matured,
                    "pending_data": result.pending_data,
                    "blocked_provenance": result.blocked_provenance,
                    "duplicate_outcomes": result.duplicate_outcomes,
                    "forward_competition": {
                        "decision_sets": result.competition_decision_sets,
                        "outcomes_appended": result.competition_outcomes_appended,
                        "pending_not_matured": result.competition_pending_not_matured,
                        "pending_data": result.competition_pending_data,
                        "blocked_provenance": result.competition_blocked_provenance,
                        "duplicate_outcomes": result.competition_duplicate_outcomes,
                    },
                    "promotion": result.promotion.model_dump(mode="json"),
                    "production_lambda": 0.0,
                    "production_llm_authority": "0%",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return int(result.exit_code)
    if action == "status":
        dashboard = service.dashboard()
        if bool(getattr(args, "json", False)):
            console.print(json.dumps(dashboard, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            _render_dashboard(dashboard)
        return 0
    if action == "readiness":
        from personal_alpha_terminal.research.data_evidence import evaluate_data_evidence
        from personal_alpha_terminal.research.forward_shadow_readiness import (
            evaluate_forward_shadow_readiness,
        )

        dashboard = service.dashboard()
        readiness = evaluate_forward_shadow_readiness(
            dashboard,
            terminal_startup=True,
            terminal_full_cycle=False,
            data_quality_status=evaluate_data_evidence().overall_status.value,
        )
        console.print(
            json.dumps(
                readiness.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if action == "doctor":
        doctor = service.doctor()
        console.print(json.dumps(doctor, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if doctor["status"] == "PASS" else int(ForwardShadowExitCode.CONFIG_ERROR)
    if action == "reconcile":
        reconciliation = service.reconcile()
        console.print(
            json.dumps(reconciliation, ensure_ascii=False, indent=2, sort_keys=True)
        )
        return 0
    console.print(f"Unknown forward-shadow action: {action}")
    return 2


def run_forward_shadow_daily(
    config: EffectiveRuntimeConfig,
    *,
    refresh: bool,
    locale: str,
) -> int:
    del locale
    _prepare(config)
    service = ForwardShadowOperations(get_session_factory(), config)
    return _run(service, decision_time=None, refresh=refresh)


def _run(
    service: ForwardShadowOperations,
    *,
    decision_time: datetime | None,
    refresh: bool,
) -> int:
    result = service.run_daily(decision_time=decision_time, refresh=refresh)
    render_daily_quant_result(result.result, console)
    _render_daily_summary(result)
    return int(result.exit_code)


def _prepare(config: EffectiveRuntimeConfig) -> None:
    upgrade_database(config.settings)
    configure_database(config.settings)


def _render_daily_summary(run: ForwardShadowRunResult) -> None:
    promotion = run.promotion
    daily = run.result
    hybrid = daily.hybrid_intelligence or {}
    counts = hybrid.get("counts") if isinstance(hybrid, dict) else {}
    count_payload = counts if isinstance(counts, dict) else {}
    console.print("\n====================================================")
    console.print("PERSONAL ALPHA TERMINAL - FORWARD SHADOW")
    console.print("====================================================")
    console.print(f"Quant Production: {'PASS' if daily.actionable else 'BLOCKED'}")
    console.print(f"Agentic Shadow: {run.state.value}")
    console.print(f"Provider: {run.identity.provider}")
    console.print(
        "Shadow decisions: "
        f"{_display_integer(count_payload.get('real_shadow_llm_decisions'))}"
    )
    console.print(f"Forward predictions appended: {run.prediction_count}")
    console.print(f"Hybrid counterfactuals appended: {run.counterfactual_count // 2}")
    console.print(
        "Real paired N: "
        f"{_display_integer(promotion.get('paired_sample_n'))} / "
        f"{_display_integer(promotion.get('minimum_required_n'))}"
    )
    console.print(
        "Independent sessions: "
        f"{_display_integer(promotion.get('unique_session_n'))} / "
        f"{_display_integer(promotion.get('minimum_unique_session_n'))}"
    )
    console.print(f"Promotion: {promotion.get('promotion_reason', 'UNAVAILABLE')}")
    console.print("Production LLM authority: 0%")
    console.print("Production lambda: 0")
    console.print("Manual action list: UNCHANGED BY LLM")
    _render_operator_summary(daily)
    console.print("====================================================")


def _render_operator_summary(daily: object) -> None:
    """Chinese-first operator answers without exposing internal object dumps."""

    market = getattr(daily, "market_regime", "UNKNOWN")
    detail = getattr(daily, "market_regime_detail", "证据不足")
    portfolio = getattr(daily, "portfolio", None)
    risk = getattr(daily, "risk", None)
    decisions = tuple(getattr(daily, "final_decisions", ()) or ())
    hybrid = getattr(daily, "hybrid_intelligence", None)
    hybrid_doc = hybrid if isinstance(hybrid, dict) else {}
    status = getattr(daily, "llm_status", "UNKNOWN")
    data_cutoff = getattr(daily, "data_cutoff", None)
    print_rows = [
        f"市场状态：{market}（{detail}）",
        f"建议总仓位：{_operator_percent(getattr(risk, 'gross_exposure', None))}",
        f"当前实际仓位：{_operator_percent(getattr(portfolio, 'invested_weight', None))}",
        f"现金比例：{_operator_percent(getattr(portfolio, 'cash_weight', None))}",
        f"今日买入：{_symbols_for_actions(decisions, {'BUY', 'ADD', 'INCREASE'})}",
        f"今日卖出：{_symbols_for_actions(decisions, {'SELL', 'REDUCE', 'DECREASE'})}",
        f"Quant 观点：{len(decisions)} 个正式决策，最终权重由 Optimizer + Risk Engine 决定",
        f"Probability 观点：{_operator_text(hybrid_doc.get('probability_view'), '仅作证据/影子')}",
        f"LLM 观点：{_operator_text(hybrid_doc.get('llm_view'), 'SHADOW / 未改变正式权重')}",
        f"Quant 与 LLM 冲突：{_operator_text(hybrid_doc.get('disagreement'), '未发现可认证分歧')}",
        f"组合最大风险：{_operator_text(getattr(risk, 'reasons', None), '以 Risk Engine 为准')}",
        "是否保持现金："
        + (
            "是"
            if (getattr(portfolio, "cash_weight", 0.0) or 0.0) > 0.5
            else "由风险门禁决定"
        ),
        "ETF 长期配置 / Alpha 操作：以 ETF sleeve 与正式股票 action 分栏为准",
        "数据完整性："
        + _operator_text(getattr(daily, "data_health", None), "以 DATA/PIT 门禁为准"),
        f"AI 状态：{status}",
        "系统是否允许执行：否，必须人工确认且自动执行 DISABLED",
        f"下一步人工操作：复核数据 cutoff {data_cutoff or 'UNAVAILABLE'}、价格、风险与买卖清单",
    ]
    console.print("\n【今日人工决策摘要】")
    for row in print_rows:
        console.print(row)


def _symbols_for_actions(decisions: tuple[object, ...], actions: set[str]) -> str:
    symbols = [
        str(getattr(item, "symbol", ""))
        for item in decisions
        if getattr(item, "action", "") in actions
    ]
    return ", ".join(symbols) if symbols else "无 / 证据积累中"


def _operator_percent(value: object) -> str:
    return f"{float(value):.2%}" if isinstance(value, (int, float)) else "证据积累中"


def _operator_text(value: object, fallback: str) -> str:
    if value is None or value == () or value == [] or value == {}:
        return fallback
    return str(value)


def _render_dashboard(dashboard: dict[str, object]) -> None:
    provider = _payload(dashboard.get("provider_health"))
    daily = _payload(dashboard.get("daily_shadow_status"))
    evidence = _payload(dashboard.get("forward_evidence"))
    promotion = _payload(dashboard.get("promotion_evidence"))
    competition = _payload(dashboard.get("forward_competition"))
    authority = _payload(dashboard.get("authority"))
    table = Table(title="PERSONAL ALPHA TERMINAL - FORWARD SHADOW OPERATIONS")
    table.add_column("Section", style="bold")
    table.add_column("Metric")
    table.add_column("Value", overflow="fold")
    for section, payload, fields in (
        (
            "Provider Health",
            provider,
            (
                "provider",
                "model",
                "configured",
                "enabled",
                "connectivity",
                "last_successful_connection",
                "last_failure",
                "attempt_count",
                "success_count",
                "failure_counts",
                "structured_response_success_rate",
                "request_count",
                "input_tokens",
                "output_tokens",
                "retry_count",
                "average_latency_ms",
                "provider_reported_cost_usd",
            ),
        ),
        (
            "Daily Shadow",
            daily,
            ("last_run", "all_transition_count", "quant_production_source"),
        ),
        (
            "Forward Evidence",
            evidence,
            (
                "total_predictions",
                "real_predictions",
                "matured_1d",
                "matured_5d",
                "matured_10d",
                "matured_20d",
                "pending_outcomes",
                "blocked_outcomes",
                "valid_paired_observations",
                "independent_sessions",
                "competition_complete_paired_sets",
                "competition_independent_sessions",
                "competition_promotion_eligible_sets",
            ),
        ),
        (
            "Five-policy Competition",
            competition,
            (
                "decision_sets",
                "frozen_variant_decisions",
                "realized_variant_outcomes",
                "pending_variant_outcomes",
                "complete_paired_sets",
                "independent_sessions",
                "promotion_eligible_paired_sets",
                "promotion_eligible_independent_sessions",
                "shadow_variant_decisions",
                "degraded_fallback_variant_decisions",
                "promotion_eligible",
            ),
        ),
        (
            "Promotion Evidence",
            promotion,
            (
                "status",
                "promotion_reason",
                "real_forward_n",
                "minimum_required_n",
                "independent_sessions",
                "minimum_sessions",
                "mean_incremental_net_alpha",
                "median_incremental_net_alpha",
                "confidence_interval",
                "lower_confidence_bound",
                "hit_rate",
                "cost_delta",
                "turnover_delta",
                "drawdown_delta",
                "calibration",
                "regime_coverage",
                "excluded_evidence_count",
                "excluded_reason_counts",
            ),
        ),
        (
            "Authority",
            authority,
            (
                "production_llm_authority",
                "production_lambda",
                "production_source",
                "execution",
            ),
        ),
    ):
        for field in fields:
            value = payload.get(field)
            rendered = (
                json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (dict, list, tuple))
                else "INSUFFICIENT_EVIDENCE"
                if value is None and section == "Promotion Evidence"
                else str(value)
            )
            table.add_row(section, field, rendered)
    console.print(table)


def _optional_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("operator timestamp must be timezone-aware")
    return parsed


def _payload(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _display_integer(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return "UNAVAILABLE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, str):
        try:
            return str(int(value))
        except ValueError:
            return "UNAVAILABLE"
    return "UNAVAILABLE"
