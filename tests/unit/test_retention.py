from datetime import UTC, datetime, timedelta
from pathlib import Path

from personal_alpha_terminal.core.retention import prune_generated_artifacts


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
