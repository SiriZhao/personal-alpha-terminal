from datetime import UTC, datetime, timedelta
from pathlib import Path

from personal_alpha_terminal.core.retention import (
    RUNTIME_ARTIFACT_POLICY,
    apply_runtime_cleanup,
    plan_runtime_cleanup,
    prune_generated_artifacts,
    runtime_artifact_status,
)


def _age(path: Path, *, now: datetime, days: int) -> None:
    stamp = (now - timedelta(days=days)).timestamp()
    path.touch()
    path.chmod(0o600)
    import os

    os.utime(path, (stamp, stamp))


def test_retention_removes_only_old_regenerated_artifacts(tmp_path: Path) -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    old_report = tmp_path / "reports" / "old.md"
    recent_report = tmp_path / "reports" / "recent.md"
    database = tmp_path / "data" / "personal_alpha.db"
    for path in (old_report, recent_report, database):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("evidence", encoding="utf-8")
    _age(old_report, now=now, days=181)
    _age(recent_report, now=now, days=2)
    _age(database, now=now, days=1000)

    removed = prune_generated_artifacts(tmp_path, now=now)

    assert removed == (old_report,)
    assert recent_report.exists()
    assert database.exists()


def _seed_governed_areas(root: Path, *, now: datetime) -> Path:
    old_daily = root / "reports" / "daily-runs" / "old-run" / "run_certificate.json"
    recent_daily = root / "reports" / "daily-runs" / "new-run" / "run_certificate.json"
    old_log = root / "var" / "logs" / "old.log"
    critical = root / "var" / "operational" / "operational_policy.json"
    research = root / "var" / "research-data" / "baselines" / "manifest.json"
    cache = root / "data" / "cache" / "yfinance" / "cookies.db"
    for path in (old_daily, recent_daily, old_log, critical, research, cache):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("evidence", encoding="utf-8")
    _age(old_daily, now=now, days=181)
    _age(recent_daily, now=now, days=2)
    _age(old_log, now=now, days=31)
    _age(critical, now=now, days=1000)
    _age(research, now=now, days=1000)
    _age(cache, now=now, days=1000)
    return old_daily


def test_runtime_artifact_status_categorizes_critical_and_cleanable_areas(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    _seed_governed_areas(tmp_path, now=now)
    rows = {str(row["area"]): row for row in runtime_artifact_status(tmp_path, now=now)}

    assert rows["reports/daily-runs"]["category"] == "DAILY_REPRODUCIBILITY"
    assert rows["reports/daily-runs"]["retention_days"] == 180
    assert rows["reports/daily-runs"]["eligible_for_cleanup"] is True
    assert rows["var/operational"]["category"] == "CRITICAL"
    assert rows["var/operational"]["eligible_for_cleanup"] is False
    assert rows["var/research-data"]["category"] == "CRITICAL"
    assert rows["data/cache"]["category"] == "CACHE"
    assert rows["data/cache"]["eligible_for_cleanup"] is False


def test_runtime_cleanup_dry_run_never_deletes(tmp_path: Path) -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    old_daily = _seed_governed_areas(tmp_path, now=now)
    planned = plan_runtime_cleanup(tmp_path, now=now, dry_run=True)

    assert old_daily.resolve() in planned
    assert old_daily.exists()
    assert (tmp_path / "var" / "operational" / "operational_policy.json").exists()
    assert (tmp_path / "var" / "research-data" / "baselines" / "manifest.json").exists()
    assert (tmp_path / "data" / "cache" / "yfinance" / "cookies.db").exists()


def test_runtime_cleanup_commit_removes_only_expired_generated_artifacts(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    old_daily = _seed_governed_areas(tmp_path, now=now)
    removed = apply_runtime_cleanup(tmp_path, now=now)

    assert old_daily.resolve() in removed
    assert not old_daily.exists()
    assert (tmp_path / "reports" / "daily-runs" / "new-run" / "run_certificate.json").exists()
    assert (tmp_path / "var" / "operational" / "operational_policy.json").exists()
    assert (tmp_path / "var" / "research-data" / "baselines" / "manifest.json").exists()
    assert (tmp_path / "data" / "cache" / "yfinance" / "cookies.db").exists()


def test_runtime_artifact_policy_contains_no_critical_cleanup_rule() -> None:
    for policy in RUNTIME_ARTIFACT_POLICY:
        if policy.retention_days is not None:
            assert policy.category in {"DAILY_REPRODUCIBILITY", "DIAGNOSTIC"}
