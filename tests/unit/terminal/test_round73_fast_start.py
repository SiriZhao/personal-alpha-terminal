"""ROUND73 fast-start safety and worker-boundary regression tests."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from io import StringIO
from pathlib import Path

from rich.console import Console

from personal_alpha_terminal.application.agentic_shadow_service import (
    _has_material_shadow_adjustment,
)
from personal_alpha_terminal.application.daily_orchestrator import (
    _agentic_shadow_is_deferred,
    _external_llm_allowed,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.terminal import cli, fast_start
from personal_alpha_terminal.terminal.fast_start import (
    build_fast_start_snapshot,
    claim_refresh_schedule,
    read_refresh_state,
    release_refresh_schedule,
    write_refresh_state,
)


def _create_fast_start_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "create table data_snapshot_manifests "
            "(snapshot_id text, completed_at text, end_date text, certification_result text)"
        )
        connection.execute("create table portfolios (id integer primary key)")
        connection.execute(
            "create table quant_decision_runs "
            "(as_of_time text, status text, gate_status text)"
        )
        connection.execute(
            "insert into data_snapshot_manifests values "
            "('snapshot-1', '2026-08-19T01:00:00+00:00', '2026-08-18', 'CERTIFIED')"
        )
        connection.execute("insert into portfolios values (1)")
        connection.execute(
            "insert into quant_decision_runs values "
            "('2026-08-18T20:30:00+00:00', 'READY', 'PASS')"
        )


def test_fast_start_displays_cached_state_but_never_marks_it_actionable(tmp_path: Path) -> None:
    database = tmp_path / "terminal.db"
    _create_fast_start_database(database)
    certificate = tmp_path / "reports" / "daily-runs" / "daily-1" / "run_certificate.json"
    certificate.parent.mkdir(parents=True)
    certificate.write_text(
        json.dumps(
            {
                "run_id": "daily-1",
                "finished_at": "2026-08-18T21:00:00+00:00",
                "decision_recommendations": [{"symbol": "AAPL"}],
            }
        ),
        encoding="utf-8",
    )

    snapshot = build_fast_start_snapshot(
        database_url=f"sqlite:///{database}",
        report_dir=tmp_path / "reports",
        refresh_state=None,
    )

    assert snapshot["state"] == "READY_STALE"
    assert snapshot["data_as_of"] == "2026-08-18"
    assert snapshot["previous_recommendation_count"] == 1
    assert snapshot["recommendation_actionable"] is False
    assert "informational" in str(snapshot["actionability_reason"])


def test_normal_daily_uses_fast_start_without_constructing_application_service(
    tmp_path: Path, monkeypatch
) -> None:
    config = EffectiveRuntimeConfig(
        report_dir=tmp_path / "reports",
        settings=Settings(database_url=f"sqlite:///{tmp_path / 'missing.db'}"),
    )
    output = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=output, color_system=None))
    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    monkeypatch.setattr(
        cli,
        "_launch_background_refresh",
        lambda *_args, **_kwargs: {"state": "SCHEDULED", "pid": 999999},
    )
    monkeypatch.setattr(
        cli,
        "_application_service",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not run in fast start")),
    )

    assert cli.main(["--config", str(tmp_path / "config.yaml"), "daily"]) == 0
    rendered = output.getvalue()
    assert "PERSONAL ALPHA TERMINAL" in rendered
    assert "不可执行" in rendered


def test_optional_external_llm_requires_positive_connectivity_status() -> None:
    assert not _external_llm_allowed(configured=False, connectivity="AVAILABLE")
    assert not _external_llm_allowed(configured=True, connectivity="NOT_TESTED")
    assert not _external_llm_allowed(configured=True, connectivity="UNAVAILABLE")
    assert _external_llm_allowed(configured=True, connectivity="AVAILABLE")


def test_zero_shadow_adjustments_do_not_require_a_duplicate_optimizer_run() -> None:
    assert not _has_material_shadow_adjustment({"AAPL": 0.0, "MSFT": -0.0})
    assert _has_material_shadow_adjustment({"AAPL": 0.001})


def test_disabled_agentic_shadow_is_deferred_from_normal_daily_hot_path() -> None:
    assert _agentic_shadow_is_deferred(
        external_enabled=False, provider_factory_configured=False
    )
    assert not _agentic_shadow_is_deferred(
        external_enabled=True, provider_factory_configured=False
    )
    assert not _agentic_shadow_is_deferred(
        external_enabled=False, provider_factory_configured=True
    )


def test_refresh_state_serializes_session_date_for_warm_path_reuse(tmp_path: Path) -> None:
    state_path = tmp_path / "terminal-refresh.json"
    write_refresh_state(state_path, {"state": "BLOCKED", "data_as_of": date(2026, 8, 18)})
    state = read_refresh_state(state_path)
    assert state is not None
    assert state["state"] == "BLOCKED"
    assert state["data_as_of"] == "2026-08-18"
    assert isinstance(state["updated_at"], str)


def test_local_database_permission_failure_is_fast_and_fail_closed(
    tmp_path: Path, monkeypatch
) -> None:
    def reject_connection(*_args, **_kwargs):
        raise sqlite3.OperationalError("permission denied: production.db")

    monkeypatch.setattr(fast_start.sqlite3, "connect", reject_connection)
    snapshot = build_fast_start_snapshot(
        database_url=f"sqlite:///{tmp_path / 'production.db'}",
        report_dir=tmp_path / "reports",
        refresh_state=None,
    )

    assert snapshot["state"] == "DEGRADED"
    assert snapshot["recommendation_actionable"] is False
    assert "permission denied" in str(snapshot["database_error"])


def test_schedule_lock_prevents_duplicate_concurrent_refresh_claims(tmp_path: Path) -> None:
    state_path = tmp_path / "terminal-refresh.json"
    assert claim_refresh_schedule(state_path)
    try:
        assert not claim_refresh_schedule(state_path)
    finally:
        release_refresh_schedule(state_path)


def test_progress_notification_publishes_refresh_state(tmp_path: Path, monkeypatch) -> None:
    config = EffectiveRuntimeConfig(
        report_dir=tmp_path / "reports",
        settings=Settings(database_url=f"sqlite:///{tmp_path / 'terminal.db'}"),
    )
    output = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=output, color_system=None))
    state_path = tmp_path / "terminal-refresh.json"

    notify = cli._progress_printer(config, state_path=state_path)
    notify("[Provider] batch 1 / 3")

    state = read_refresh_state(state_path)
    assert state is not None
    assert state["state"] == "REFRESHING"
    assert state["processed"] == 1
    assert state["total"] == 3
    assert state["current_stage"] == "[Provider] batch 1 / 3"
