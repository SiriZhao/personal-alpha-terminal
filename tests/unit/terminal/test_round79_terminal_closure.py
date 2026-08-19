"""ROUND79 compact operator terminal regressions."""

from __future__ import annotations

import json
import sqlite3
from io import StringIO
from pathlib import Path

from rich.console import Console

from personal_alpha_terminal.terminal import cli
from personal_alpha_terminal.terminal.fast_start import build_fast_start_snapshot


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "create table data_snapshot_manifests "
            "(snapshot_id text, completed_at text, end_date text, certification_result text)"
        )
        connection.execute(
            "create table portfolios (id integer primary key, cash_balance numeric)"
        )
        connection.execute(
            "create table quant_decision_runs (as_of_time text, status text, gate_status text)"
        )
        connection.execute(
            "create table portfolio_risk_runs "
            "(id integer primary key, status text, created_at text)"
        )
        connection.execute(
            "create table portfolio_risk_metrics (run_id integer, total_value numeric)"
        )
        connection.execute(
            "create table portfolio_positions (as_of_date text, quantity numeric)"
        )
        connection.execute(
            "create table intelligence_research_results (result_type text, payload text)"
        )
        connection.execute(
            "insert into data_snapshot_manifests values "
            "('snapshot-79', '2026-08-19T01:00:00+00:00', '2026-08-18', "
            "'BLOCKED_DATA_QUALITY')"
        )
        connection.execute("insert into portfolios values (1, 1250.50)")
        connection.execute(
            "insert into quant_decision_runs values ('2026-08-18T20:30:00+00:00', 'READY', 'PASS')"
        )
        connection.execute(
            "insert into portfolio_risk_runs values (1, 'completed', '2026-08-18T21:00:00+00:00')"
        )
        connection.execute("insert into portfolio_risk_metrics values (1, 3250.50)")
        connection.execute("insert into portfolio_positions values ('2026-08-18', 2)")
        connection.execute("insert into portfolio_positions values ('2026-08-18', 0)")
        connection.execute(
            "insert into intelligence_research_results values (?, ?)",
            (
                "FORWARD_COMPETITION_DECISION_SET",
                json.dumps(
                    {
                        "competition_id": "competition-79",
                        "tournament": {"decision_time": "2026-08-18T20:30:00+00:00"},
                    }
                ),
            ),
        )
        for variant in (
            "PURE_QUANT",
            "QUANT_PLUS_PROBABILITY",
            "QUANT_PLUS_LLM",
            "QUANT_PLUS_PROBABILITY_PLUS_LLM",
            "FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE",
        ):
            connection.execute(
                "insert into intelligence_research_results values (?, ?)",
                (
                    "FORWARD_COMPETITION_OUTCOME",
                    json.dumps(
                        {
                            "competition_id": "competition-79",
                            "evaluation_horizon": "1d",
                            "outcome": {"variant": variant},
                        }
                    ),
                ),
            )


def test_fast_start_operator_frame_is_compact_chinese_and_fail_closed(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "round79.db"
    _database(database)
    snapshot = build_fast_start_snapshot(
        database_url=f"sqlite:///{database}",
        report_dir=tmp_path / "reports",
        refresh_state={
            "state": "REFRESHING",
            "current_stage": "provider batch",
            "processed": 3,
            "total": 11,
            "elapsed_seconds": 2.0,
            "last_progress_at": "2026-08-19T01:00:00+00:00",
        },
    )

    assert snapshot["portfolio_value"] == 3250.5
    assert snapshot["cash_balance"] == 1250.5
    assert snapshot["holding_count"] == 1
    assert snapshot["forward_paired_observations"] == 1
    assert snapshot["forward_independent_sessions"] == 1
    assert snapshot["recommendation_actionable"] is False
    assert snapshot["next_blocker"] == "DATA_PIT_OR_SURVIVORSHIP_GATE"

    output = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=output, color_system=None))
    cli._startup_panel(snapshot)
    rendered = output.getvalue()
    assert "组合市值" in rendered
    assert "数据新鲜度" in rendered
    assert "研究数据认证" in rendered
    assert "Forward 配对样本" in rendered
    assert "下一阻断项" in rendered
    assert "不可执行" in rendered
