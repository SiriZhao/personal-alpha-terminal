from __future__ import annotations

from io import StringIO

from rich.console import Console

from personal_alpha_terminal.terminal import cli


def test_persisted_decision_render_is_compact_and_hides_raw_trace_dump() -> None:
    certificate = {
        "run_id": "daily-fixture",
        "decision_counts": {"BUY": 1, "SELL": 0, "HOLD": 2, "REJECTED": 0},
        "decision_traces": {"AAA": {"factor_raw_values": {"x": 1.0}}},
        "decision_recommendations": [
            {
                "symbol": "AAA",
                "action": "BUY",
                "current_weight": 0.0,
                "target_weight": 0.1,
                "expected_alpha": 0.02,
                "reason": "PIT-safe quantified signal",
            }
        ],
    }
    stream = StringIO()
    original = cli.console
    cli.console = Console(file=stream, width=120, color_system=None)
    try:
        cli._render_persisted_decisions(certificate)
    finally:
        cli.console = original
    output = stream.getvalue()
    assert "今日正式建议" in output
    assert "AAA" in output
    assert "LLM authority" in output
    assert "factor_raw_values" not in output
    assert "详细 factor/trace 字段保留" in output
