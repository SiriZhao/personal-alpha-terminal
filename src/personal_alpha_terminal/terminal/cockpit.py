"""ROUND39 read-only Chinese daily decision cockpit.

This renderer only reads persisted backend artifacts. It never recomputes
alpha, target weights, risk, or BUY/SELL decisions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def _read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"backend artifact missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"backend artifact is not an object: {path}")
    return payload


def render_daily_cockpit(
    console: Console,
    *,
    reports_root: Path,
    run_id: str,
) -> int:
    provenance = _read_json(
        reports_root / "daily-runs" / run_id / "decision_provenance.json"
    )
    round34 = _read_json(
        reports_root / "validation-artifacts" / "round34_validation_summary.json"
    )
    round33 = _read_json(
        reports_root
        / "validation-artifacts"
        / "round33_corrected_oos_performance.json"
    )
    round37 = _read_json(
        reports_root / "validation-artifacts" / "round37_validation_summary.json"
    )
    decisions_raw = provenance.get("decisions", {})
    decisions = cast(dict[str, object], decisions_raw) if isinstance(decisions_raw, dict) else {}
    first_decision = next(iter(decisions.values()), {})
    first_decision = cast(dict[str, object], first_decision)
    optimizer_raw = first_decision.get("optimizer", {})
    optimizer = cast(dict[str, object], optimizer_raw) if isinstance(optimizer_raw, dict) else {}
    provenance_raw = optimizer.get("portfolio_provenance", {})
    provenance_obj = (
        cast(dict[str, object], provenance_raw)
        if isinstance(provenance_raw, dict)
        else {}
    )
    champion_raw = round33.get("champion", {})
    champion = (
        cast(dict[str, object], champion_raw)
        if isinstance(champion_raw, dict)
        else {}
    )
    champion_perf_raw = champion.get("performance", {})
    champion_perf = (
        cast(dict[str, object], champion_perf_raw)
        if isinstance(champion_perf_raw, dict)
        else {}
    )

    console.print(Panel(f"每日决策驾驶舱 | {run_id}", title="【今日运行状态】"))
    console.print(
        "DATA/PIT/FACTOR/ALPHA/PORTFOLIO/RISK gates: "
        "见当日 run certificate; cockpit 只读已持久化结果"
    )

    table = Table(title="【当前账户与模型目标】")
    table.add_column("字段")
    table.add_column("值")
    table.add_row("optimizer input", str(provenance_obj.get("optimizer_input_count")))
    table.add_row("pre-optimizer Top-N", str(provenance_obj.get("pre_optimizer_top_n")))
    table.add_row("fixed holdings cap", str(None))
    table.add_row("formal action count", str(provenance_obj.get("final_target_count")))
    table.add_row("gross", str(optimizer.get("portfolio_gross_weight")))
    table.add_row("cash", str(optimizer.get("portfolio_cash_weight")))
    table.add_row("expected vol", str(optimizer.get("portfolio_expected_volatility")))
    console.print(table)

    console.print(
        Panel(
            "Probability: "
            + str(round37.get("PROBABILITY_PRODUCTION_INFLUENCE", "0"))
            + "\nLLM: advisory only, 不参与正式量化权重计算\n"
            "ETF: 观察/研究/正式动作严格分离",
            title="【模型解释与 AI 边界】",
        )
    )

    performance_table = Table(title="【模型成绩 - ROUND33 corrected research】")
    performance_table.add_column("指标")
    performance_table.add_column("Champion")
    performance_table.add_row("total return", str(champion_perf.get("total_return")))
    performance_table.add_row("annualized return", str(champion_perf.get("annualized_return")))
    performance_table.add_row("Sharpe", str(champion_perf.get("sharpe")))
    performance_table.add_row("Max DD", str(champion_perf.get("maximum_drawdown")))
    performance_table.add_row(
        "real forward evidence",
        str(round34.get("REALIZED_FORWARD_EVIDENCE", "INSUFFICIENT_SAMPLE")),
    )
    console.print(performance_table)

    console.print(
        Panel(
            "人工检查清单：确认 run id；确认账户 NAV/cash/holdings；只执行已接受建议；"
            "不在终端中自动下单。",
            title="【今日人工执行检查】",
        )
    )
    return 0
