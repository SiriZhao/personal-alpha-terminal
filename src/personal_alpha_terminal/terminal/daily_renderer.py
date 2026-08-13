from __future__ import annotations

import unicodedata
from contextvars import ContextVar
from io import StringIO

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from personal_alpha_terminal.application.daily_result import (
    DailyQuantResult,
    StageStatus,
)

_ACTIVE_LOCALE: ContextVar[str] = ContextVar("daily_renderer_locale", default="zh-CN")


def render_daily_quant_result(
    result: DailyQuantResult, console: Console, *, locale: str = "zh-CN"
) -> None:
    """Render one immutable result. No model, gate or trade calculation lives here."""

    if locale not in {"zh-CN", "en-US"}:
        raise ValueError("locale must be zh-CN or en-US")
    token = _ACTIVE_LOCALE.set(locale)
    try:
        console.print(
            Panel(
                _header(result),
                title=_t(
                    "PERSONAL ALPHA TERMINAL · 个人量化交易终端",
                    "PERSONAL ALPHA TERMINAL · DAILY QUANT REPORT",
                ),
                border_style="cyan",
            )
        )
        _today_actions(result, console)
        _operational_status(result, console)
        _portfolio(result, console)
        _benchmark(result, console)
        _market(result, console)
        _ai_intelligence(result, console)
        _market_data(result, console)
        _data_certification(result, console)
        _pit_universe(result, console)
        _data_health(result, console)
        _factors(result, console)
        _probability(result, console)
        _risk(result, console)
        _decisions(result, console)
        _execution(result, console)
        _rejected(result, console)
        _blocker_center(result, console)
        _pipeline(result, console)
        _run_certificate(result, console)
        _summary(result, console)
    finally:
        _ACTIVE_LOCALE.reset(token)


def capture_daily_quant_result(
    result: DailyQuantResult, *, width: int = 120, locale: str = "en-US"
) -> str:
    stream = StringIO()
    console = Console(file=stream, width=width, color_system=None, force_terminal=False)
    render_daily_quant_result(result, console, locale=locale)
    return stream.getvalue()


def _ai_intelligence(result: DailyQuantResult, console: Console) -> None:
    stage = next(
        (item for item in result.stages if item.name == "LLM_INTELLIGENCE"),
        None,
    )
    if stage is None:
        return
    metadata = stage.metadata
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold cyan")
    table.add_column()
    advisory_status = str(metadata.get("advisory_status", "SHADOW"))
    advisory_impact = str(metadata.get("advisory_quant_impact", "NONE"))
    advisory_impact_text = "SHADOW" if advisory_impact == "SHADOW" else "NO"
    rows = (
        (_t("\u72b6\u6001", "Status"), _status_text(stage.status)),
        (
            _t("Provider / \u6a21\u578b", "Provider / model"),
            f"{metadata.get('provider', '--')} / {metadata.get('model', '--')}",
        ),
        (
            _t("LLM 连接", "Connectivity"),
            str(metadata.get("connectivity", "NOT_TESTED")),
        ),
        (_t("SEC 原文", "Raw SEC documents"), str(metadata.get("raw_documents", 0))),
        (
            _t("发行人已解析", "Issuer resolved documents"),
            str(metadata.get("issuer_resolved_documents", 0)),
        ),
        (
            _t("安全已映射", "Security mapped documents"),
            str(metadata.get("security_mapped_documents", 0)),
        ),
        (_t("新增文档", "New documents"), str(metadata.get("new_documents", 0))),
        (
            _t("PIT 合格文档", "PIT-eligible documents"),
            str(metadata.get("pit_eligible_documents", 0)),
        ),
        (_t("LLM 调用", "LLM calls"), str(metadata.get("llm_calls", 0))),
        (_t("缓存命中", "Cache hits"), str(metadata.get("cache_hits", 0))),
        (
            _t("\u5df2\u5904\u7406\u6587\u6863", "Processed documents"),
            str(metadata.get("processed_documents", 0)),
        ),
        (_t("PIT \u4e8b\u4ef6", "PIT events"), str(metadata.get("detected_events", 0))),
        (
            _t("已接受事件", "Accepted events"),
            str(metadata.get("accepted_events", metadata.get("detected_events", 0))),
        ),
        (
            _t("隔离事件", "Quarantined events"),
            str(metadata.get("quarantined_events", 0)),
        ),
        (
            _t("SHADOW \u56e0\u5b50\u89c2\u6d4b", "SHADOW factor observations"),
            str(metadata.get("shadow_factor_observations", 0)),
        ),
        (
            _t("最新事件时间", "Latest event time"),
            str(metadata.get("latest_event_time") or "--"),
        ),
        (
            _t("预计 API 成本", "Estimated API cost"),
            f"${float(str(metadata.get('estimated_api_cost_usd', 0.0))):.6f}",
        ),
        (
            _t("\u56e0\u5b50\u72b6\u6001", "Factor status"),
            str(metadata.get("factor_status", "UNAVAILABLE")),
        ),
        (
            _t("\u751f\u4ea7\u5f71\u54cd", "Production influence"),
            "NO" if not metadata.get("production_influence") else "YES",
        ),
        (_t("AI \u72b6\u6001", "AI status"), advisory_status),
        (_t("\u91cf\u5316\u51b3\u7b56\u5f71\u54cd", "Quant impact"), advisory_impact_text),
        (
            _t("\u5b89\u5168\u56de\u9000", "Safe fallback"),
            str(metadata.get("fallback", "CLASSICAL_CHAMPION")),
        ),
    )
    for label, value in rows:
        table.add_row(label, value)
    console.print(
        Panel(
            table,
            title=_t("\u3010AI \u60c5\u62a5\u3011", "AI INTELLIGENCE"),
            border_style="yellow",
        )
    )


def _layered_status(result: DailyQuantResult) -> str:
    data_status = next(
        (stage.status for stage in result.stages if stage.name == "DATA"),
        None,
    )
    data_ready = data_status in {StageStatus.PASS, StageStatus.PASS_DEGRADED}
    quant_ready = result.diagnostic_analysis_complete
    portfolio_ready = result.portfolio.status != "NOT_INITIALIZED"
    risk_ready = result.risk.status == "PASS"
    trading_actionable = result.actionable
    if _is_zh():
        return (
            f"数据 {'●通过' if data_ready else '●阻塞'}   "
            f"量化 {'●完成' if quant_ready else '○未完成'}   "
            f"组合 {'●就绪' if portfolio_ready else '●需初始化'}   "
            f"风险 {'●通过' if risk_ready else '○待运行'}   "
            f"交易建议 {'●可执行' if trading_actionable else '●当前不可执行'}   "
            f"LLM {result.llm_status}"
        )
    return (
        f"DATA {'READY' if data_ready else 'BLOCKED'}   QUANT "
        f"{'READY' if quant_ready else 'NOT READY'}   PORTFOLIO "
        f"{'READY' if portfolio_ready else 'REQUIRED'}   RISK "
        f"{'READY' if risk_ready else 'NOT RUN'}   TRADING "
        f"{'ACTIONABLE' if trading_actionable else 'BLOCKED'}   LLM {result.llm_status}"
    )


def _header(result: DailyQuantResult) -> str:
    classification = {
        "CERTIFIED_ACTIONABLE": "ACTIONABLE TRADING PLAN · MANUAL EXECUTION ONLY",
        "CERTIFIED_NO_ACTION": "CERTIFIED NO-ACTION RUN",
        "PROVISIONAL_ACTIONABLE": "PROVISIONAL OPERATIONAL ACTION · MANUAL ONLY",
        "PROVISIONAL_NO_ACTION": "PROVISIONAL NO-ACTION RUN",
        "VALID_ANALYSIS_ACTIONABLE_CERTIFIED": (
            "CERTIFIED ACTIONABLE ANALYSIS / MANUAL EXECUTION ONLY"
        ),
        "VALID_ANALYSIS_ACTIONABLE_PROVISIONAL": (
            "PROVISIONAL ADVISORY / MANUAL REVIEW ONLY"
        ),
        "VALID_ANALYSIS_NON_ACTIONABLE": (
            "VALID QUANT ANALYSIS / NON-ACTIONABLE\nFORMAL TRADING DECISION NOT AVAILABLE"
        ),
        "INVALID_NON_ACTIONABLE": "INVALID / NON-ACTIONABLE QUANT RUN\nDO NOT USE FOR TRADING",
    }[result.run_classification]
    raw_latest = max(
        (item.latest_date for item in result.data_health if item.latest_date),
        default=None,
    )
    data_through = (
        result.data_cutoff.isoformat()
        if result.data_cutoff
        else (f"{raw_latest} (raw only; PIT cutoff unavailable)" if raw_latest else "UNAVAILABLE")
    )
    if _is_zh():
        classification = {
            "VALID_ANALYSIS_ACTIONABLE_CERTIFIED": (
                "CERTIFIED ACTIONABLE / MANUAL EXECUTION ONLY"
            ),
            "VALID_ANALYSIS_ACTIONABLE_PROVISIONAL": (
                "PROVISIONAL ADVISORY / MANUAL REVIEW ONLY"
            ),
            "CERTIFIED_ACTIONABLE": "可执行 · 仅生成外部券商手动执行计划",
            "CERTIFIED_NO_ACTION": "无需操作 · 全部正式门禁已通过",
            "PROVISIONAL_ACTIONABLE": "试运行量化可操作 · 仅手动执行",
            "PROVISIONAL_NO_ACTION": "试运行无需操作",
            "VALID_ANALYSIS_NON_ACTIONABLE": "量化分析有效 · 当前不可生成正式交易建议",
            "INVALID_NON_ACTIONABLE": "运行无效 · 不得用于交易",
        }[result.run_classification]
        return (
            f"{classification}\n\n日期 {result.started_at.date()}   "
            f"分析日 {result.analysis_date}   "
            f"交易日 {result.trade_date}\n市场 {result.market_session}   "
            f"数据截止 {data_through}\nRun ID {result.run_id}   "
            f"耗时 {result.duration_seconds:.2f}s\n"
            f"{_layered_status(result)}"
        )
    return (
        f"{classification}\n\nVersion {result.version}   Run {result.run_id}\n"
        f"ET/Market session {result.market_session}   Analysis {result.analysis_date}   "
        f"Trade {result.trade_date}\n"
        f"Data through {data_through}   "
        f"Duration {result.duration_seconds:.2f}s\n"
        f"{_layered_status(result)}"
    )


def _today_actions(result: DailyQuantResult, console: Console) -> None:
    title = _t("【今日操作清单】", "TODAY ACTION LIST")
    if not result.final_decisions:
        headline = (
            _t("今日无需操作", "NO ACTION TODAY")
            if result.actionable
            else _t("今日无法生成正式建议", "FORMAL RECOMMENDATION UNAVAILABLE")
        )
        reason = _primary_blocker(result)
        console.print(
            Panel(
                f"{headline}\n\n{_t('主要原因', 'Primary reason')}: {reason}\n"
                + _t(
                    "候选不等于正式信号；正式建议仅在策略、组合与风险门禁全部通过后生成。",
                    "A candidate is not a formal signal; strategy, portfolio and "
                    "risk gates must pass.",
                ),
                title=title,
                border_style="green" if result.actionable else "red",
            )
        )
        return
    if result.operationally_allowed:
        console.print(
            Panel(
                "Advice class: PROVISIONAL_ADVISORY\n"
                f"Research certification: {result.research_certification_state}\n"
                f"Operational authorization: {result.operational_policy_decision}\n"
                "Automatic execution: DISABLED",
                title=title,
                border_style="yellow",
            )
        )
    table = Table(title=title)
    columns = (
        (
            "代码",
            "操作",
            "当前权重",
            "目标权重",
            "调整",
            "预计金额",
            "数量",
            "Alpha",
            "风险",
            "最早执行",
        )
        if _is_zh()
        else (
            "Ticker",
            "Action",
            "Current",
            "Target",
            "Delta",
            "Value",
            "Qty",
            "Alpha",
            "Risk",
            "Earliest",
        )
    )
    for column in columns:
        table.add_column(column, overflow="fold")
    for item in result.final_decisions:
        table.add_row(
            item.symbol,
            _action(item.action),
            _percent(item.current_weight),
            _percent(item.target_weight),
            _signed_percent(item.delta_weight),
            _money(item.estimated_value),
            str(item.estimated_quantity),
            _signed_percent(item.expected_alpha),
            _t("通过", "PASS"),
            item.earliest_execution_time.isoformat(),
        )
    console.print(table)


def _operational_status(result: DailyQuantResult, console: Console) -> None:
    statuses = {item.name: item.status for item in result.stages}

    def ok(name: str) -> bool:
        return statuses.get(name) in {StageStatus.PASS, StageStatus.PASS_DEGRADED}

    research = (
        _t("未完全认证", "NOT_CERTIFIABLE")
        if result.research_certification_state.upper() == "NOT_CERTIFIABLE"
        else result.research_certification_state
    )
    data = _t("通过", "PASS") if ok("DATA") else _t("阻塞", "BLOCKED")
    pit = _t("通过", "PASS") if ok("PIT") else _t("阻塞", "BLOCKED")
    signal = _t("通过", "PASS") if ok("SIGNAL") else _t("阻塞", "BLOCKED")
    risk = _t("通过", "PASS") if ok("RISK") else _t("阻塞", "BLOCKED")
    policy = (
        _t(
            f"允许降级生产建议（{result.operational_policy_id}）",
            f"ALLOW PROVISIONAL ({result.operational_policy_id})",
        )
        if result.operationally_allowed
        else _t("未配置 / 拒绝", "NOT_CONFIGURED / BLOCKED")
    )
    if not result.operationally_allowed:
        policy = (
            f"{result.operational_policy_decision} "
            f"({result.operational_policy_id}; {result.operational_policy_reason})"
        )
    final_state = (
        _t("可操作（降级）", "ACTIONABLE (DEGRADED)")
        if result.operationally_allowed
        else _t("不可操作", "NOT_ACTIONABLE")
    )
    if result.operationally_allowed:
        policy_explanation = _t(
            "当前建议未获得完整历史研究认证，但已根据显式 Operational Policy "
            "允许进入生产建议。该状态不代表研究认证通过。",
            "Current advice is allowed by an explicit Operational Policy but is not "
            "full research certification. This status does not mean research is certified.",
        )
    elif result.operational_policy_id != "NOT_CONFIGURED":
        policy_explanation = _t(
            "已保存的 Operational Policy 当前不生效，生产建议保持阻断。"
            f"原因：{result.operational_policy_reason}。",
            "The stored Operational Policy is not effective; production recommendations "
            f"remain blocked. Reason: {result.operational_policy_reason}.",
        )
    else:
        policy_explanation = _t(
            "当前没有生效的 Operational Policy，生产建议保持阻断。",
            "No effective Operational Policy is configured; production recommendations "
            "remain blocked.",
        )
    body = _t(
        f"【研究认证】{research}\n"
        f"【生产数据】{data}\n"
        f"【PIT】{pit}\n"
        f"【量化信号】{signal}\n"
        f"【风控】{risk}\n"
        f"【运行策略】{policy}\n"
        f"【最终状态】{final_state}\n\n"
        f"{policy_explanation}",
        f"Research certification: {research}\n"
        f"Data: {data}\n"
        f"PIT: {pit}\n"
        f"Signal: {signal}\n"
        f"Risk: {risk}\n"
        f"Operational policy: {policy}\n"
        f"Final: {final_state}\n\n"
        f"{policy_explanation}",
    )
    console.print(
        Panel(
            body,
            title=_t("研究认证与运行策略", "RESEARCH / OPERATIONAL POLICY"),
            border_style="yellow",
        )
    )


def _pipeline(result: DailyQuantResult, console: Console) -> None:
    table = Table(title=_t("正式流水线 · 严格关闭", "PIPELINE · FAIL CLOSED"), show_lines=False)
    table.add_column(_t("阶段", "Stage"), style="bold")
    table.add_column(_t("状态", "Status"))
    table.add_column(_t("耗时", "Time"), justify="right")
    table.add_column(_t("说明", "Message"), overflow="fold")
    for stage in result.stages:
        table.add_row(
            stage.name,
            _status_text(stage.status),
            f"{stage.duration_seconds:.2f}s",
            stage.message,
        )
    console.print(table)


def _market_data(result: DailyQuantResult, console: Console) -> None:
    """Market data panel: data mode, providers, coverage, verdict."""
    data_stage = next((item for item in result.stages if item.name == "DATA"), None)
    data_meta = data_stage.metadata if data_stage is not None else {}
    llm_stage = next((item for item in result.stages if item.name == "LLM_INTELLIGENCE"), None)
    llm_meta = llm_stage.metadata if llm_stage is not None else {}
    data_mode = str(result.provenance.get("data_mode", "CACHE_REPLAY"))
    expected = result.analysis_date
    latest = next(
        (item.latest_date for item in result.data_health if item.latest_date),
        None,
    )
    coverage = next(
        (item.coverage for item in result.data_health if item.coverage is not None),
        None,
    )
    provider = str(data_meta.get("provider", "UNAVAILABLE"))
    primary = "yahoo" if "yahoo" in provider.lower() else provider
    fallback = str(llm_meta.get("provider", "--"))
    verdict = _market_data_verdict(data_stage)
    live_refresh_status = str(data_meta.get("live_refresh_status", "LIVE_REFRESH_FAIL"))
    requested_securities = str(data_meta.get("requested_security_count", "N/A"))
    actual_refresh = str(data_meta.get("actual_refresh_count", "N/A"))
    cache_reuse = str(data_meta.get("cache_reuse_count", "N/A"))
    provider_returned = str(data_meta.get("provider_returned_count", "N/A"))
    certified_coverage = _as_float(data_meta.get("certified_coverage"))
    quarantine = str(data_meta.get("quarantine_count", "N/A"))
    provider_incident = str(data_meta.get("provider_incident_count", "N/A"))
    collapse = "YES" if data_meta.get("coverage_collapse") else "NO"
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold cyan")
    table.add_column()
    rows = (
        (_t("\u4ea4\u6613\u65e5", "Trade date"), str(result.trade_date)),
        (_t("\u5206\u6790\u65e5", "Analysis date"), str(result.analysis_date)),
        (
            _t("\u9884\u671f\u6700\u65b0\u5b8c\u6210\u4ea4\u6613\u65e5", "Expected latest session"),
            str(expected),
        ),
        (
            _t("\u5b9e\u9645\u6700\u65b0\u4ea4\u6613\u65e5", "Actual latest session"),
            str(latest or "UNAVAILABLE"),
        ),
        (_t("\u6570\u636e\u6a21\u5f0f", "Data mode"), data_mode),
        (_t("\u4e3b\u6570\u636e\u6e90", "Primary provider"), primary),
        (_t("\u5907\u7528\u6570\u636e\u6e90", "Fallback provider"), fallback),
        (_t("\u5237\u65b0\u72b6\u6001", "Live refresh"), live_refresh_status),
        (_t("\u8bf7\u6c42\u8bc1\u5238", "Requested securities"), requested_securities),
        (_t("\u5b9e\u9645\u5237\u65b0", "Actual refresh"), actual_refresh),
        (_t("\u7f13\u5b58\u590d\u7528", "Cache reuse"), cache_reuse),
        (_t("Provider \u8fd4\u56de", "Provider returned"), provider_returned),
        (_t("\u8ba4\u8bc1\u8986\u76d6", "Certified coverage"), _percent(certified_coverage)),
        (_t("\u9694\u79bb", "Quarantine"), quarantine),
        (_t("Provider \u4e8b\u4ef6", "Provider incident"), provider_incident),
        (_t("\u8986\u76d6\u574d\u5854", "Coverage collapse"), collapse),
        (_t("\u6570\u636e\u8986\u76d6", "Coverage"), _percent(coverage)),
        (
            _t("\u5e02\u573a\u6570\u636e\u7ed3\u8bba", "Market data verdict"),
            verdict,
        ),
    )
    for label, value in rows:
        table.add_row(label, value)
    console.print(
        Panel(
            table,
            title=_t("\u3010\u5e02\u573a\u6570\u636e\u3011", "MARKET DATA"),
            border_style=(
                "red"
                if verdict.startswith("BLOCKED")
                else "yellow"
                if verdict == "PASS_DEGRADED"
                else "green"
            ),
        )
    )


def _market_data_verdict(data_stage: object) -> str:
    """Derive a one-line market-data verdict from the DATA stage status."""
    from personal_alpha_terminal.application.daily_result import StageStatus

    if data_stage is None:
        return "BLOCKED_STALE_DATA"
    status = getattr(data_stage, "status", None)
    if status is StageStatus.PASS:
        return "PASS"
    if status is StageStatus.PASS_DEGRADED:
        return "PASS_DEGRADED"
    if status in {StageStatus.FAIL, StageStatus.FAIL_BLOCKING}:
        message = str(getattr(data_stage, "message", "")).lower()
        if "provider" in message or "refresh" in message:
            return "BLOCKED_PROVIDER_FAILURE"
        if "stale" in message:
            return "BLOCKED_STALE_DATA"
        if "coverage" in message or "collapse" in message:
            return "BLOCKED_COVERAGE_COLLAPSE"
        return "BLOCKED_STALE_DATA"
    return "PASS_DEGRADED"


def _data_certification(result: DailyQuantResult, console: Console) -> None:
    stage = next((item for item in result.stages if item.name == "DATA"), None)
    evidence = stage.metadata if stage is not None else {}
    body = (
        f"Status {stage.status.value if stage else 'NOT_RUN'}   "
        f"Provider {evidence.get('provider', 'UNAVAILABLE')}\n"
        f"Snapshot {evidence.get('snapshot_id', 'UNAVAILABLE')}   "
        "Refresh requested symbols "
        f"{_item_count(evidence.get('requested_symbols'))}   "
        "Provider-returned symbols "
        f"{_item_count(evidence.get('received_symbols'))}   "
        "PIT-certified symbols "
        f"{_item_count(evidence.get('certified_symbols'))}   "
        f"Rejected {_item_count(evidence.get('rejected_symbols'))}   "
        f"Missing {_item_count(evidence.get('missing_symbols'))}   "
        f"Stale {_item_count(evidence.get('stale_symbols'))}\n"
        f"Bars expected {evidence.get('expected_bars', 0)}   "
        f"matched {evidence.get('matched_bars', 0)}   "
        f"unexpected {evidence.get('unexpected_bars', 0)}   "
        f"quarantined {evidence.get('quarantined_bars', 0)}   "
        f"missing {evidence.get('missing_bars', 0)}   "
        f"received {evidence.get('received_bars', 0)}   "
        f"valid {evidence.get('valid_bars', 0)}   "
        "Certified-bar coverage "
        f"{_percent(_as_float(evidence.get('coverage')))}   "
        f"Cache reused {evidence.get('cache_reused', 'NOT_REPORTED')}\n"
        f"Latest {evidence.get('latest_timestamp', 'UNAVAILABLE')}   "
        f"PIT cutoff {result.data_cutoff.isoformat() if result.data_cutoff else 'UNAVAILABLE'}\n"
        f"Corporate actions {evidence.get('corporate_action_status', 'NOT_CERTIFIED')}   "
        f"PIT integrity {evidence.get('pit_integrity_status', 'NOT_CERTIFIED')}   "
        f"Freshness {evidence.get('freshness_status', 'NOT_CERTIFIED')}   "
        f"Duplicates {evidence.get('duplicate_rows', 0)}   "
        f"Invalid OHLC {evidence.get('invalid_ohlc', 0)}   "
        f"Future rows {evidence.get('future_rows', 0)}   "
        f"Timezone violations {evidence.get('timezone_violations', 0)}"
    )
    fallback_usage = evidence.get("fallback_usage", ())
    if isinstance(fallback_usage, (list, tuple)) and fallback_usage:
        fallback_table = Table(title="FALLBACK USED")
        fallback_table.add_column("Ticker")
        fallback_table.add_column("Provider")
        fallback_table.add_column("Reason", overflow="fold")
        for item in fallback_usage:
            if isinstance(item, dict):
                fallback_table.add_row(
                    str(item.get("symbol", "--")),
                    str(item.get("provider", "--")),
                    str(item.get("reason", "primary request failed")),
                )
        console.print(fallback_table)
    console.print(
        Panel(
            body,
            title=_t("数据认证", "DATA CERTIFICATION"),
            border_style=(
                "green"
                if stage and stage.status is StageStatus.PASS
                else "yellow"
                if stage and stage.status is StageStatus.PASS_DEGRADED
                else "red"
            ),
        )
    )
    matrix = evidence.get("symbol_matrix", ())
    rejected = (
        [item for item in matrix if isinstance(item, dict) and item.get("final") != "CERTIFIED"]
        if isinstance(matrix, (list, tuple))
        else []
    )
    if rejected:
        table = Table(title="REJECTED DATA")
        table.add_column("Ticker")
        table.add_column("Required")
        table.add_column("Gate")
        table.add_column("Reason", overflow="fold")
        for item in rejected:
            gate = "DATA"
            if item.get("primary") != "PASS":
                gate = "PRIMARY/CALENDAR"
            elif item.get("corporate_action") not in {"PASS", "PASS_WITH_WARNING"}:
                gate = "CORPORATE_ACTION"
            table.add_row(
                str(item.get("symbol", "--")),
                "YES" if item.get("required") else "NO",
                gate,
                str(item.get("reason", "unavailable")),
            )
        console.print(table)


def _pit_universe(result: DailyQuantResult, console: Console) -> None:
    stage = next((item for item in result.stages if item.name == "PIT"), None)
    evidence = stage.metadata if stage is not None else {}
    data_stage = next((item for item in result.stages if item.name == "DATA"), None)
    data_evidence = data_stage.metadata if data_stage is not None else {}
    universe = result.provenance.get("universe_evidence", {})
    universe = universe if isinstance(universe, dict) else {}
    funnel = universe.get("funnel")
    funnel = funnel if isinstance(funnel, dict) else {}
    historical = universe.get("historical_research")
    historical = historical if isinstance(historical, dict) else {}
    collapse = universe.get("collapse")
    collapse = collapse if isinstance(collapse, dict) else {}
    candidates = universe.get("candidate_compression")
    candidates = candidates if isinstance(candidates, dict) else {}
    qualification = universe.get("qualification", "UNAVAILABLE")
    quarantine_count = universe.get("quarantine_count", "UNAVAILABLE")
    collapse_text = (
        f"COLLAPSE DETECTED: {collapse.get('reason', '')}"
        if collapse.get("detected")
        else "no collapse detected"
    )
    candidate_lines = ""
    steps = candidates.get("steps", [])
    if isinstance(steps, list) and steps:
        step_text = "  ".join(
            f"{step.get('name')}={step.get('count')}"
            for step in steps
            if isinstance(step, dict)
        )
        candidate_lines = (
            "Candidate funnel\n"
            f"{step_text}\n"
            f"Candidates into optimizer {universe.get('candidate_count', 'UNAVAILABLE')}   "
            f"Full factor rows {universe.get('full_factor_count', 'UNAVAILABLE')}\n"
        )
    historical_lines = ""
    if historical:
        historical_lines = (
            "Historical research tier (HISTORICAL_RESEARCH_PIT)\n"
            f"Security type {historical.get('security_type_eligible', 0)}   "
            f"Data {historical.get('data_eligible', 0)}   "
            f"Liquidity {historical.get('liquidity_eligible', 0)}   "
            f"Factor {historical.get('factor_eligible', 0)}\n"
        )
    listed = funnel.get(
        "listed_securities",
        universe.get("raw_listed_securities", "UNAVAILABLE"),
    )
    equities = funnel.get(
        "listed_equities",
        universe.get("raw_listed_equities", "UNAVAILABLE"),
    )
    security_ok = funnel.get(
        "security_type_eligible", universe.get("security_type_eligible", 0)
    )
    price_ok = funnel.get("latest_price_covered", "UNAVAILABLE")
    history_ok = funnel.get("history_sufficient", "UNAVAILABLE")
    pit_ok = funnel.get(
        "pit_eligible", funnel.get("data_eligible", universe.get("data_eligible", 0))
    )
    liq_ok = funnel.get(
        "liquidity_eligible", universe.get("liquidity_eligible", 0)
    )
    factor_ok = funnel.get(
        "factor_eligible", universe.get("factor_eligible", 0)
    )
    tradable_ok = funnel.get(
        "signal_eligible", universe.get("signal_eligible", 0)
    )
    alpha_positive = universe.get("alpha_positive", "UNAVAILABLE")
    candidate_count = universe.get("candidate_count", "UNAVAILABLE")
    optimizer_input = universe.get("optimizer_input", candidate_count)
    cardinality = result.provenance.get("cardinality_trace", {})
    cardinality = cardinality if isinstance(cardinality, dict) else {}
    max_holdings = cardinality.get("maximum_allowed_holdings")
    optimized_holdings = cardinality.get(
        "optimized_target_holdings", len(result.portfolio.positions)
    )
    risk_engine_securities = cardinality.get("risk_engine_securities", "UNAVAILABLE")
    final_holdings = cardinality.get(
        "final_decision_holdings", len(result.portfolio.positions)
    )
    console.print(
        Panel(
            f"Status {stage.status.value if stage else 'NOT_RUN'}   "
            f"Rows {evidence.get('output_row_count', 0)}\n"
            f"Qualification {qualification}   "
            f"Survivorship {universe.get('survivorship_status', 'UNVERIFIED')}\n"
            "Current operational universe funnel\n"
            f"US listed securities {listed}   Listed equities {equities}\n"
            f"Security type eligible {security_ok}   Latest-price covered {price_ok}\n"
            f"History-sufficient {history_ok}   PIT eligible {pit_ok}   "
            f"Liquidity eligible {liq_ok}\n"
            f"Factor eligible {factor_ok}   Alpha positive {alpha_positive}   "
            f"{_t('\u5019\u9009\u6c60', 'Candidate pool')} {candidate_count}\n"
            f"{_t('\u4f18\u5316\u5668\u8f93\u5165', 'Optimizer input')} {optimizer_input}   "
            f"{_t('\u4f18\u5316\u540e\u76ee\u6807\u6301\u4ed3', 'Optimized holdings')} "
            f"{optimized_holdings}\n"
            f"{_t('\u6700\u5927\u5141\u8bb8\u6301\u4ed3', 'Maximum allowed holdings')} "
            f"{max_holdings if max_holdings is not None else 'UNLIMITED'}   "
            f"Risk compared {risk_engine_securities}   Final decisions {final_holdings}\n"
            f"Pre-optimizer Top10 {bool(cardinality.get('pre_optimizer_top10_truncation'))}   "
            f"Optimizer Top10-only {bool(cardinality.get('optimizer_received_alpha_top10'))}\n"
            f"Operational tradable {tradable_ok}   "
            f"Quarantine {quarantine_count}\n"
            + candidate_lines
            + historical_lines
            + f"Coverage guard: {collapse_text}\n"
            + "As-of cutoff "
            f"{result.data_cutoff.isoformat() if result.data_cutoff else 'UNAVAILABLE'}\n"
            "Latest completed session "
            f"{data_evidence.get('latest_completed_session', result.analysis_date)}\n"
            "Decision convention "
            f"{data_evidence.get('decision_timestamp_convention', 'UNAVAILABLE')}\n"
            f"PIT status {universe.get('pit_status', 'UNAVAILABLE')}   "
            f"Message: {stage.message if stage else 'PIT stage was not created'}",
            title=_t("PIT / \u80a1\u7968\u6c60", "PIT / UNIVERSE"),
            border_style=(
                "green"
                if stage and stage.status is StageStatus.PASS
                else "yellow"
                if stage and stage.status is StageStatus.PASS_DEGRADED
                else "red"
            ),
        )
    )


def _data_health(result: DailyQuantResult, console: Console) -> None:
    table = Table(title=_t("数据健康 · 仅限策略输入", "DATA HEALTH · STRATEGY INPUTS ONLY"))
    narrow = console.width < 100
    columns = (
        ("Dataset", "Latest / Expected", "Source", "Status", "Detail")
        if narrow
        else (
            "Dataset",
            "Expected",
            "Latest",
            "Age",
            "Coverage",
            "Missing",
            "Source",
            "Status",
            "Detail",
        )
    )
    for column in columns:
        table.add_column(column, overflow="fold")
    if not result.data_health:
        empty = (
            ("PIT DATASET", "-- / --", "UNAVAILABLE", "FAIL", "No canonical input")
            if narrow
            else (
                "PIT DATASET",
                "--",
                "--",
                "--",
                "--",
                "--",
                "UNAVAILABLE",
                "FAIL",
                "No canonical strategy input was available",
            )
        )
        table.add_row(*empty)
    for item in result.data_health:
        row = (
            (
                item.dataset,
                f"{item.latest_date or '--'} / {item.expected_date or '--'}",
                item.source,
                item.status.value,
                item.detail or "--",
            )
            if narrow
            else (
                item.dataset,
                str(item.expected_date or "--"),
                str(item.latest_date or "--"),
                str(item.age_days) if item.age_days is not None else "--",
                _percent(item.coverage),
                _percent(item.missing_ratio),
                item.source,
                item.status.value,
                item.detail or "--",
            )
        )
        table.add_row(*row)
    console.print(table)


def _market(result: DailyQuantResult, console: Console) -> None:
    console.print(
        Panel(
            f"State: {result.market_regime}\n{result.market_regime_detail}\n"
            f"Structure: {result.market_structure}",
            title=_t("市场状态（可选）", "MARKET REGIME"),
        )
    )


def _portfolio(result: DailyQuantResult, console: Console) -> None:
    summary = result.portfolio
    onboarding = (
        "\nQuant diagnostics remain available. Formal trading decisions require:\n"
        "  portfolio-init\n  or portfolio-import"
        if summary.status == "NOT_INITIALIZED"
        else ""
    )
    lifecycle = result.provenance.get("lifecycle")
    lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
    pnl = lifecycle.get("pnl")
    pnl = pnl if isinstance(pnl, dict) else {}
    attribution = lifecycle.get("attribution")
    attribution = attribution if isinstance(attribution, dict) else {}
    reconciliation = lifecycle.get("reconciliation")
    reconciliation = reconciliation if isinstance(reconciliation, list) else []
    pnl_lines = ""
    if pnl:
        pnl_lines = (
            f"Unrealized P&L {_money(pnl.get('unrealized_pnl'))}   "
            f"Realized P&L {_money(pnl.get('realized_pnl'))}   "
            f"Cost basis {_money(pnl.get('total_cost_basis'))}\n"
        )
    attribution_lines = ""
    if attribution:
        attribution_lines = (
            f"Beginning NAV {_money(attribution.get('beginning_nav'))}   "
            f"Ending NAV {_money(attribution.get('ending_nav'))}\n"
            f"Market P&L {_money(attribution.get('market_pnl'))}   "
            f"Trading P&L {_money(attribution.get('trading_pnl'))}   "
            f"Fees {_money(attribution.get('fees'))}\n"
            f"Portfolio return {_percent(attribution.get('portfolio_return'))}   "
            f"Benchmark return {_percent(attribution.get('benchmark_return'))}   "
            f"Active return {_percent(attribution.get('active_return'))}\n"
        )
    reconciliation_lines = ""
    required = [
        item
        for item in reconciliation
        if isinstance(item, dict) and item.get("status") == "RECONCILIATION_REQUIRED"
    ]
    if required:
        reconciliation_lines = (
            "Corporate action reconciliation required (no auto-adjustment):\n"
            + "\n".join(
                f"  {item.get('symbol')}: {item.get('actions')}" for item in required
            )
            + "\n"
        )
    console.print(
        Panel(
            f"{_t('\u7ec4\u5408 ID', 'Portfolio ID')} "
            f"{result.provenance.get('portfolio_id', 'UNSELECTED')}   "
            f"Status {summary.status}\nNAV {_money(summary.nav)}   Cash {_money(summary.cash)}   "
            f"Invested {_percent(summary.invested_weight)}   "
            f"Cash weight {_percent(summary.cash_weight)}\n"
            + pnl_lines
            + attribution_lines
            + reconciliation_lines
            + onboarding,
            title=_t(
                "\u300a\u6295\u8d44\u7ec4\u5408\u300b \u00b7 \u624b\u5de5\u7ef4\u62a4\u8d26\u672c",
                "LIVE PORTFOLIO \u00b7 MANUAL LEDGER",
            ),
        )
    )
    table = Table()
    zh_columns = (
        "\u4ee3\u7801",
        "\u80a1\u6570",
        "\u4ef7\u683c",
        "\u5f53\u524d\u6743\u91cd",
        "\u76ee\u6807\u6743\u91cd",
        "\u8c03\u6574",
    )
    en_columns = ("Ticker", "Shares", "Price", "Current", "Target", "Delta")
    columns = zh_columns if _is_zh() else en_columns
    for column in columns:
        table.add_column(column, justify="right" if column != "Ticker" else "left")
    if not summary.positions:
        table.add_row(
            _t("\u5f53\u524d\u65e0\u6301\u4ed3", "NO POSITIONS"),
            "--", "--", "0.00%", "--", "--",
        )
    for item in summary.positions:
        table.add_row(
            item.symbol,
            f"{item.shares:g}" if item.shares is not None else "--",
            f"{item.price:.2f}" if item.price is not None else "--",
            _percent(item.current_weight),
            _percent(item.target_weight),
            _signed_percent(item.delta_weight),
        )
    console.print(table)
    if summary.cash_weight is not None:
        console.print(f"{_t('\u73b0\u91d1', 'Cash'):8} {_bar(summary.cash_weight, 20)}")
        console.print(f"{_t('\u80a1\u7968', 'Equity')} {_bar(summary.invested_weight or 0.0, 20)}")


def _factors(result: DailyQuantResult, console: Console) -> None:
    table = Table(title=_t("因子 / Alpha · 候选 ≠ 交易", "FACTOR / ALPHA · CANDIDATE ≠ TRADE"))
    component_names = (
        []
        if console.width < 100
        else sorted({name for row in result.factors for name in row.components})
    )
    table.add_column("Rank", justify="right")
    table.add_column("Ticker")
    for name in component_names:
        table.add_column(name[:12], justify="right")
    table.add_column("Composite", justify="right")
    table.add_column("Exp Alpha", justify="right")
    table.add_column("Evidence", justify="right")
    table.add_column("Status")
    if not result.candidates:
        table.add_row(
            "--",
            "NO VALID CANDIDATES",
            *("--" for _ in component_names),
            "--",
            "--",
            "--",
            "DIAGNOSTIC ONLY",
        )
    for row in result.candidates:
        table.add_row(
            str(row.rank),
            row.symbol,
            *(f"{row.components.get(name, 0.0):+.2f}" for name in component_names),
            f"{row.composite:+.2f}",
            _signed_percent(row.expected_alpha),
            _percent(row.evidence_coverage),
            row.status,
        )
    console.print(table)
    for row in result.candidates[:8]:
        normalized = max(0.0, min(1.0, (row.composite + 3.0) / 6.0))
        console.print(f"{row.symbol:7} {_bar(normalized, 16)}  {row.composite:+.2f}")


def _probability(result: DailyQuantResult, console: Console) -> None:
    overlay = result.provenance.get("probability_overlay", {})
    overlay = overlay if isinstance(overlay, dict) else {}
    active = bool(overlay.get("active", False))
    runtime_state = "ACTIVE_CALIBRATED" if active else "FALLBACK_CLASSICAL"
    console.print(
        _t(
            f"\u6761\u4ef6\u6982\u7387\u8bc4\u4f30: COMPLETED   "
            f"OOS incremental value: {'PROVED' if active else 'NOT PROVED'}   "
            f"\u751f\u4ea7\u6743\u91cd: {'ACTIVE' if active else '0%'}   "
            f"Mode: {runtime_state}\n"
            f"Overlay {overlay.get('state', 'RESEARCH_ONLY')}   "
            f"Active {active}   "
            f"Reason {overlay.get('reason', 'UNAVAILABLE')}",
            f"Probability assessment: COMPLETED   "
            f"OOS incremental value: {'PROVED' if active else 'NOT PROVED'}   "
            f"Production weight: {'ACTIVE' if active else '0%'}   "
            f"Mode: {runtime_state}\n"
            f"Overlay {overlay.get('state', 'RESEARCH_ONLY')}   "
            f"Active {active}   "
            f"Reason {overlay.get('reason', 'UNAVAILABLE')}",
        )
    )
    changed = [
        trace
        for trace in (result.decision_traces or {}).values()
        if trace.get("decision_changed_without_probability") is True
    ]
    console.print(
        "If Probability is disabled, today's recommendation changes: "
        f"{'YES' if changed else 'NO'}"
    )
    traces = [
        trace
        for trace in (result.decision_traces or {}).values()
        if "target_without_probability" in trace
    ]
    if traces:
        trace_table = Table(title="Probability -> Target Weight counterfactual")
        trace_columns = (
            "Ticker",
            "Base alpha",
            "P(cond)",
            "Target off",
            "Target on",
            "Impact",
            "Decision off",
            "Final",
        )
        for column in trace_columns:
            trace_table.add_column(column, overflow="fold")
        for trace in traces[:10]:
            trace_table.add_row(
                str(trace.get("ticker", "--")),
                _signed_percent(_as_float(trace.get("base_alpha"))),
                _percent(_as_float(trace.get("conditional_probability"))),
                _percent(_as_float(trace.get("target_without_probability"))),
                _percent(_as_float(trace.get("target_with_probability"))),
                _signed_percent(_as_float(trace.get("probability_weight_impact"))),
                str(trace.get("decision_without_probability", "--")),
                str(trace.get("final_decision", "--")),
            )
        console.print(trace_table)
    formation = [
        trace
        for trace in (result.decision_traces or {}).values()
        if trace.get("target_weight") is not None
    ]
    if formation:
        formation_table = Table(
            title=_t("\u51b3\u7b56\u5f62\u6210\u8fc7\u7a0b", "DECISION FORMATION PROCESS")
        )
        for column in (
            "Ticker",
            "Factor rank",
            "Base alpha",
            "Probability",
            "Prob adjustment",
            "Risk target",
            "Final target",
            "Trade delta",
            "Final decision",
        ):
            formation_table.add_column(column, overflow="fold")
        for trace in formation[:10]:
            probability = trace.get("conditional_probability")
            formation_table.add_row(
                str(trace.get("ticker", trace.get("symbol", "--"))),
                str(trace.get("cross_sectional_rank", "--")),
                _signed_percent(_as_float(trace.get("base_alpha"))),
                (
                    _percent(_as_float(probability))
                    if probability is not None
                    else "N/A (CLASSICAL FALLBACK)"
                ),
                _signed_percent(
                    (
                        _as_float(trace.get("probability_adjusted_alpha"))
                        or _as_float(trace.get("base_alpha"))
                        or 0.0
                    )
                    - (_as_float(trace.get("base_alpha")) or 0.0)
                ),
                _percent(_as_float(trace.get("risk_adjusted_target"))),
                _percent(_as_float(trace.get("final_trade_target"))),
                _signed_percent(_as_float(trace.get("delta_weight"))),
                str(
                    trace.get(
                        "final_decision",
                        trace.get("final_action", "--"),
                    )
                ),
            )
        console.print(formation_table)
    table = Table(
        title=_t(
            "条件概率 · 仅作支持证据 · 未校准时不可调整仓位",
            "CONDITIONAL PROBABILITY · SUPPORTING EVIDENCE ONLY",
        )
    )
    narrow = console.width < 100
    columns = (
        ("Condition", "N", "P(cond)", "Lift", "Reliability / OOS")
        if narrow
        else (
            "Condition",
            "Target",
            "N",
            "Hits",
            "P(cond)",
            "P(base)",
            "Lift",
            "Avg",
            "Median",
            "Std",
            "CI",
            "Reliability",
            "OOS",
        )
    )
    for column in columns:
        table.add_column(column, overflow="fold")
    for row in result.probabilities:
        interval = (
            f"[{row.credible_interval[0]:.1%}, {row.credible_interval[1]:.1%}]"
            if row.credible_interval
            else "--"
        )
        values = (
            (
                row.condition,
                str(row.sample_size),
                _percent(row.conditional_probability),
                _signed_percent(row.lift),
                f"{row.reliability}; {row.oos_status}",
            )
            if narrow
            else (
                row.condition,
                row.target,
                str(row.sample_size),
                str(row.hits) if row.hits is not None else "--",
                _percent(row.conditional_probability),
                _percent(row.base_probability),
                _signed_percent(row.lift),
                _signed_percent(row.average_return),
                _signed_percent(row.median_return),
                _percent(row.return_std),
                interval,
                row.reliability,
                row.oos_status,
            )
        )
        table.add_row(*values)
    console.print(table)
    for row in result.probabilities:
        if row.conditional_probability is not None:
            console.print(f"  {row.condition[:28]:28} {_bar(row.conditional_probability)}")


def _risk(result: DailyQuantResult, console: Console) -> None:
    risk = result.risk
    stress_notes = (*risk.stress_failures, *risk.stress_warnings)
    console.print(
        Panel(
            f"Correlation {risk.correlation_status}: "
            f"recent {_number(risk.recent_average_correlation)} / "
            f"baseline {_number(risk.baseline_average_correlation)} / "
            f"jump {_number(risk.correlation_jump)} "
            f"(N={risk.correlation_sample_count})\n"
            f"Size exposure {risk.size_exposure_status}   Stress {risk.stress_status}\n"
            + (
                "Stress evidence: " + "; ".join(stress_notes)
                if stress_notes
                else "Stress evidence: no veto or warning"
            ),
            title=_t(
                "风险证据 · 相关性 / 规模 / 压力", "RISK EVIDENCE · CORRELATION / SIZE / STRESS"
            ),
            border_style="yellow" if risk.stress_status != "PASS" else "green",
        )
    )
    size = risk.size_diagnostics
    size = size if isinstance(size, dict) else {}
    size_status = str(size.get("status", risk.size_exposure_status))
    bucket_counts = size.get("candidate_size_bucket_counts", {})
    bucket_counts = bucket_counts if isinstance(bucket_counts, dict) else {}
    bucket_line = " ".join(
        f"{name}={bucket_counts.get(name, 'N/A')}"
        for name in ("micro_cap", "small_cap", "mid_cap", "large_cap", "mega_cap")
    )
    console.print(
        Panel(
            f"Size verdict {size_status}\n"
            f"Coverage {_percent(_as_float(size.get('coverage_ratio')))}   "
            f"Valid {size.get('market_cap_valid_count', 'N/A')}   "
            f"Missing {size.get('market_cap_missing_count', 'N/A')}\n"
            f"Candidate buckets: {bucket_line}\n"
            f"Portfolio weighted average "
            f"{_money(_as_float(size.get('portfolio_weighted_average_market_cap')))}\n"
            f"Portfolio weighted median "
            f"{_money(_as_float(size.get('portfolio_weighted_median_market_cap')))}\n"
            f"Portfolio size percentile "
            f"{_percent(_as_float(size.get('portfolio_weighted_size_percentile')))}\n"
            f"Small/micro exposure {_percent(_as_float(size.get('final_small_micro_exposure')))}\n"
            f"Largest bucket {size.get('final_size_bucket_concentration', 'N/A')} "
            f"{_percent(_as_float(size.get('final_largest_size_bucket_weight')))}\n"
            f"Smallest holding cap {_money(_as_float(size.get('smallest_holding_market_cap')))}\n"
            f"Liquidity percentile {_percent(_as_float(size.get('liquidity_percentile')))}\n"
            f"ADV {_money(_as_float(size.get('average_daily_dollar_volume')))}   "
            f"Spread proxy {size.get('spread_proxy_bps', 'N/A')} bps   "
            f"Impact {_number(_as_float(size.get('expected_market_impact_bps')))} bps",
            title=_t(
                "SIZE_TILT_DIAGNOSTIC \u00b7 \u89c4\u6a21\u503e\u659c\u8bca\u65ad",
                "SIZE_TILT_DIAGNOSTIC",
            ),
            border_style="yellow" if size_status != "SIZE_EXPOSURE_VALIDATED" else "green",
        )
    )
    console.print(
        Panel(
            f"Gate {risk.status}   Expected vol {_percent(risk.expected_volatility)}   "
            f"Target vol {_percent(risk.target_volatility)}   HHI {_number(risk.hhi)}\n"
            f"Largest target {_percent(risk.largest_target_weight)}   "
            f"Gross {_percent(risk.gross_exposure)} → Cash {_percent(risk.cash_target)}   "
            f"Turnover {_percent(risk.turnover)}\n"
            + ("Reasons: " + "; ".join(risk.reasons) if risk.reasons else "Reasons: none"),
            title=_t(
                "【风险控制】· 原始目标 → 风险调整目标", "RISK · RAW TARGET → RISK-ADJUSTED TARGET"
            ),
            border_style="yellow" if risk.status != "PASS" else "green",
        )
    )
    gauges = (
        (_t("总仓位", "Gross"), risk.gross_exposure, 0.90),
        (_t("最大单票", "Largest"), risk.largest_target_weight, 0.12),
        (_t("换手率", "Turnover"), risk.turnover, 0.30),
    )
    for label, value, limit in gauges:
        if value is None:
            console.print(f"{label:8} -- / {_percent(limit)}")
        else:
            console.print(
                f"{label:8} {_bar(value / limit if limit else 0.0, 14)}  "
                f"{_percent(value)} / {_percent(limit)}"
            )


def _decisions(result: DailyQuantResult, console: Console) -> None:
    table = Table(
        title=_t(
            "\u6700\u7ec8\u6709\u6548\u51b3\u7b56 "
            "\u00b7 \u4ec5\u663e\u793a\u6b63\u5f0f\u4e70\u5356\u533a",
            "FINAL VALIDATED DECISIONS ? ONLY FORMAL BUY/SELL AREA",
        )
    )
    narrow = console.width < 100
    columns = (
        ("Ticker", "Action", "Current → Target", "Value", "Reason")
        if narrow
        else (
            "Ticker",
            "Action",
            "Current",
            "Target",
            "Delta",
            "Value",
            "Alpha",
            "Confidence",
            "Confidence Source",
            "Risk",
            "Reason",
        )
    )
    for column in columns:
        table.add_column(column, overflow="fold")
    if not result.final_decisions:
        action = "NO_ACTION" if result.actionable else "NOT_ACTIONABLE"
        reason = (
            "Complete certified pipeline produced no rebalance outside the no-trade band"
            if result.actionable
            else "Required stages did not complete; no trading judgment was generated"
        )
        empty = (
            (
                "ALL",
                action,
                "-- → --",
                "--",
                reason,
            )
            if narrow
            else (
                "ALL",
                action,
                "--",
                "--",
                "--",
                "--",
                "--",
                "--",
                "--",
                "BLOCKED",
                reason,
            )
        )
        table.add_row(*empty)
    for item in result.final_decisions:
        shown_action = _semantic_action(
            item.action,
            current_weight=item.current_weight,
            target_weight=item.target_weight,
        )
        values = (
            (
                item.symbol,
                shown_action,
                f"{_percent(item.current_weight)} → {_percent(item.target_weight)}",
                _money(item.estimated_value),
                item.reason,
            )
            if narrow
            else (
                item.symbol,
                shown_action,
                _percent(item.current_weight),
                _percent(item.target_weight),
                _signed_percent(item.delta_weight),
                _money(item.estimated_value),
                _signed_percent(item.expected_alpha),
                _confidence(item.confidence),
                item.confidence_source,
                f"{item.risk_contribution:.3f}",
                item.reason,
            )
        )
        table.add_row(*values)
    console.print(table)


def _rejected(result: DailyQuantResult, console: Console) -> None:
    table = Table(
        title=_t(
            "\u88ab\u62d2\u7edd\u4fe1\u53f7 / \u95e8\u7981\u539f\u56e0",
            "REJECTED SIGNALS / GATE BLOCKERS",
        )
    )
    table.add_column("Ticker")
    table.add_column("Rejected by")
    table.add_column("Reason", overflow="fold")
    if not result.rejected_signals:
        table.add_row("--", "--", "None")
    for item in result.rejected_signals:
        table.add_row(item.symbol, item.rejected_by, item.reason)
    console.print(table)


def _blocker_center(result: DailyQuantResult, console: Console) -> None:
    primary, secondary, optional = _classified_blockers(result)
    body = "\n".join(
        (
            f"{_t('主要', 'Primary')}: " + ("; ".join(primary) or _t("无", "None")),
            f"{_t('次要', 'Secondary')}: " + ("; ".join(secondary) or _t("无", "None")),
            f"{_t('可选缺失', 'Optional')}: " + ("; ".join(optional) or _t("无", "None")),
        )
    )
    console.print(
        Panel(
            body,
            title=_t("阻塞与拒绝原因", "BLOCKERS AND REJECTIONS"),
            border_style="red" if primary else "yellow" if secondary or optional else "green",
        )
    )


def _classified_blockers(
    result: DailyQuantResult,
) -> tuple[list[str], list[str], list[str]]:
    primary: list[str] = []
    secondary: list[str] = []
    optional: list[str] = []
    values = list(dict.fromkeys((*result.blockers, *result.warnings)))
    for value in values:
        upper = value.upper()
        if "OPTIONAL" in upper or "REGIME" in upper:
            optional.append(value)
        elif "PROBABILITY" in upper or "INSUFFICIENT_SAMPLE" in upper or "UNCALIBRATED" in upper:
            secondary.append(value)
        else:
            primary.append(value)
    return primary, secondary, optional


def _primary_blocker(result: DailyQuantResult) -> str:
    primary, secondary, optional = _classified_blockers(result)
    values = primary or secondary or optional
    return (
        values[0]
        if values
        else _t("无；正式门禁通过但无需调仓", "None; gates passed with no rebalance")
    )


def _execution(result: DailyQuantResult, console: Console) -> None:
    plan = result.execution_plan
    execution_state = "NOT_EXECUTED"
    table = Table(
        title=_t(
            f"\u6267\u884c\u8ba1\u5212\uff1a{plan.status} \u00b7 "
            f"\u5238\u5546\u6267\u884c\uff1a{execution_state} \u00b7 "
            f"\u6267\u884c\u65b9\u5f0f\uff1a{plan.execution_mode}",
            f"EXECUTION PLAN ? {plan.status} ? BROKER {execution_state} ? "
            f"{plan.execution_mode}",
        )
    )
    for column in ("#", "Ticker", "Action", "Est Value", "Qty", "Est Cost", "Earliest"):
        table.add_column(column, overflow="fold")
    if not plan.legs:
        table.add_row("--", "--", "NO EXECUTION", "--", "--", "--", "--")
    for leg in plan.legs:
        table.add_row(
            str(leg.sequence),
            leg.symbol,
            leg.action,
            _money(leg.estimated_value),
            str(leg.estimated_quantity),
            _money(leg.estimated_cost),
            leg.earliest_execution_time.isoformat(),
        )
    console.print(table)
    console.print(
        _t(
            f"\u6267\u884c\u8ba1\u5212\uff1a"
            f"{'PASS' if plan.execution_plan_generated else 'BLOCKED'}   "
            f"\u5238\u5546\u6267\u884c\uff1aNOT_EXECUTED   "
            f"\u6267\u884c\u65b9\u5f0f\uff1a{plan.execution_mode}   "
            f"\u5238\u5546\uff1a{plan.broker}   Broker API {plan.broker_api}\n"
            f"execution_plan_generated={str(plan.execution_plan_generated).lower()}   "
            f"broker_order_submitted={str(plan.broker_order_submitted).lower()}",
            f"EXECUTION PLAN: {'PASS' if plan.execution_plan_generated else 'BLOCKED'}   "
            f"BROKER: NOT_EXECUTED   MODE: {plan.execution_mode}   "
            f"BROKER: {plan.broker}   Broker API {plan.broker_api}\n"
            f"execution_plan_generated={str(plan.execution_plan_generated).lower()}   "
            f"broker_order_submitted={str(plan.broker_order_submitted).lower()}",
        )
    )
    console.print(
        f"Cash before {_money(plan.estimated_cash_before)}  "
        f"+ Proceeds {_money(plan.estimated_proceeds)}  "
        f"- Buys {_money(plan.estimated_buys)}  - Costs {_money(plan.estimated_cost)}  "
        f"= Cash after {_money(plan.estimated_cash_after)}"
    )


def _benchmark(result: DailyQuantResult, console: Console) -> None:
    console.print(
        Panel(
            _t(
                "前向实际运行记录：main 组合已建立 T0 账本；首个同步收盘观察尚未完成。\n"
                "Portfolio / SPY / QQQ 同起点曲线：待首个合法观察点。Sharpe、CAGR、"
                "Sortino、年化 Alpha：样本不足。",
                "FORWARD LIVE TRACK: the main ledger has a T0; the first synchronized "
                "close observation is pending. Portfolio/SPY/QQQ normalized curves and "
                "annualized statistics: INSUFFICIENT_SAMPLE.",
            ),
            title=_t("前向实际运行记录", "FORWARD LIVE TRACK RECORD"),
            border_style="yellow",
        )
    )
    table = Table(
        title=_t(
            "市场与基准 · 与策略使用相同 PIT 约定",
            "BENCHMARK · SAME PIT DATA CONVENTION AS STRATEGY",
        )
    )
    for column in (
        "Benchmark",
        "Status",
        "Start",
        "End",
        "N",
        "Period Return",
        "Ann Vol",
        "Max DD",
        "Note",
    ):
        table.add_column(column, overflow="fold")
    if not result.benchmarks:
        table.add_row(
            "--",
            "UNAVAILABLE",
            "--",
            "--",
            "0",
            "--",
            "--",
            "--",
            "No certified comparable sample",
        )
    for item in result.benchmarks:
        table.add_row(
            item.name,
            item.status,
            str(item.start_date or "--"),
            str(item.end_date or "--"),
            str(item.observation_count),
            _signed_percent(item.period_return),
            _percent(item.annualized_volatility),
            _signed_percent(item.max_drawdown),
            item.note,
        )
    console.print(table)
    comparable = [
        abs(item.period_return) for item in result.benchmarks if item.period_return is not None
    ]
    scale = max(comparable, default=0.0)
    for item in result.benchmarks:
        if item.period_return is not None:
            normalized = abs(item.period_return) / scale if scale > 0 else 0.0
            console.print(
                f"{item.name:10} {_bar(normalized, 16)} {_signed_percent(item.period_return)}"
            )
    cost = result.provenance.get("transaction_cost_assumption")
    if isinstance(cost, str) and cost:
        console.print(f"Cost assumption: {cost}")


def _run_certificate(result: DailyQuantResult, console: Console) -> None:
    console.print(
        Panel(
            f"Classification: {result.run_classification}\n"
            f"Run ID: {result.run_id}\n"
            f"Data hash: {result.provenance.get('data_hash', 'UNAVAILABLE')}\n"
            f"Config hash: {result.config_hash}\n"
            f"Models: {', '.join(result.model_versions) or 'UNAVAILABLE'}\n"
            f"Research certification: {result.research_certification_state}\n"
            f"Operational authorization: {result.operational_policy_decision}\n"
            f"Policy ID: {result.operational_policy_id}\n"
            f"Signal authorization: "
            f"{result.provenance.get('signal_authorization_class', 'FAIL_BLOCKING')}\n"
            "Automatic execution: DISABLED / MANUAL_ONLY\n"
            f"Certificate: {result.certificate_path or 'UNAVAILABLE'}",
            title=_t("运行证书 · 专业审计信息", "RUN CERTIFICATE"),
            border_style="green" if result.actionable else "red",
        )
    )


def _summary(result: DailyQuantResult, console: Console) -> None:
    buys = sum(item.action in {"BUY", "ADD", "INCREASE"} for item in result.final_decisions)
    sells = sum(item.action in {"SELL", "REDUCE"} for item in result.final_decisions)
    blockers = "; ".join(result.blockers) if result.blockers else "None"
    data_status = next(
        (stage.status.value for stage in result.stages if stage.name == "DATA"),
        "UNKNOWN",
    )
    if not result.actionable:
        valid_analysis = result.diagnostic_analysis_complete
        conclusion = (
            "VALID QUANT ANALYSIS - FORMAL TRADING DECISION UNAVAILABLE"
            if valid_analysis
            else "INVALID / NON-ACTIONABLE QUANT RUN - DO NOT USE FOR TRADING"
        )
        narrative = _t(
            "今日数据认证通过，但策略尚未满足生产认证要求，因此未生成正式交易操作。"
            if result.diagnostic_analysis_complete
            else "今日正式流水线未通过，未生成任何交易操作。",
            conclusion,
        )
        console.print(
            Panel(
                f"Run {result.run_classification}   Pipeline {result.decision_readiness.value}   "
                f"Data {data_status}   Portfolio {result.portfolio.status}   "
                f"Risk {result.risk.status}\n"
                f"Actions 0   Blockers: {blockers}\n\n" + narrative,
                title=_t("今日总结", "TODAY SUMMARY"),
                border_style="yellow" if valid_analysis else "red",
            )
        )
        return
    console.print(
        Panel(
            f"Run {result.run_classification}   Pipeline {result.decision_readiness.value}   "
            f"Data {data_status}   "
            f"Portfolio {result.portfolio.status}   Risk {result.risk.status}\n"
            f"Actions {len(result.execution_plan.legs)}   Buy/Add {buys}   Sell/Reduce {sells}   "
            f"Turnover {_percent(result.execution_plan.turnover)}   "
            f"Cash after {_money(result.execution_plan.estimated_cash_after)}\n"
            f"Blockers: {blockers}\n\nMANUAL EXECUTION REQUIRED · CHARLES SCHWAB · NO BROKER API",
            title=_t("今日总结", "TODAY SUMMARY"),
            border_style="green" if result.actionable else "red",
        )
    )


def _status_text(status: StageStatus) -> Text:
    style = {
        StageStatus.PASS: "green",
        StageStatus.PASS_DEGRADED: "yellow",
        StageStatus.OPTIONAL_UNAVAILABLE: "yellow",
        StageStatus.FAIL_BLOCKING: "red bold",
        StageStatus.NOT_RUN: "dim",
    }[status]
    label = {
        StageStatus.PASS: _t("通过（PASS）", "PASS"),
        StageStatus.PASS_DEGRADED: _t("降级通过（PASS_DEGRADED）", "PASS_DEGRADED"),
        StageStatus.OPTIONAL_UNAVAILABLE: _t("可选不可用", "OPTIONAL_UNAVAILABLE"),
        StageStatus.FAIL_BLOCKING: _t("阻塞（FAIL_BLOCKING）", "FAIL_BLOCKING"),
        StageStatus.NOT_RUN: _t("未运行（NOT_RUN）", "NOT_RUN"),
    }[status]
    return Text(label, style=style)


def _bar(value: float, width: int = 30) -> str:
    bounded = max(0.0, min(1.0, value))
    filled = round(bounded * width)
    # U+2591 is not encodable on legacy Windows GBK terminals. Keep the filled
    # Unicode block and use an ASCII remainder so CMD/PowerShell fail gracefully.
    return "█" * filled + "-" * (width - filled) + f" {bounded:.1%}"


def display_width(value: str) -> int:
    """Return terminal cell width for mixed CJK/Latin text."""

    width = 0
    for character in value:
        if unicodedata.combining(character):
            continue
        width += 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
    return width


def _is_zh() -> bool:
    return _ACTIVE_LOCALE.get() == "zh-CN"


def _t(zh: str, en: str) -> str:
    return zh if _is_zh() else en


def _semantic_action(value: str, *, current_weight: float, target_weight: float) -> str:
    """ROUND 6 user-facing action: SELL of a full position is EXIT."""
    from personal_alpha_terminal.portfolio.lifecycle import semantic_action

    return semantic_action(
        value,
        current_weight=current_weight,
        target_weight=target_weight,
    )


def _action(value: str) -> str:
    if not _is_zh():
        return value
    return {
        "BUY": "买入",
        "ADD": "增持",
        "INCREASE": "增持",
        "SELL": "卖出",
        "REDUCE": "减持",
        "HOLD": "持有",
        "NO_ACTION": "无需操作",
    }.get(value, value)


def _percent(value: float | None) -> str:
    return f"{value:.2%}" if value is not None else "--"


def _confidence(value: float | None) -> str:
    return f"{value:.2%}" if value is not None else "N/A"


def _signed_percent(value: float | None) -> str:
    return f"{value:+.2%}" if value is not None else "--"


def _money(value: float | None) -> str:
    return f"${value:,.2f}" if value is not None else "--"


def _number(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "--"


def _as_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _item_count(value: object) -> int:
    return len(value) if isinstance(value, (list, tuple, set)) else 0