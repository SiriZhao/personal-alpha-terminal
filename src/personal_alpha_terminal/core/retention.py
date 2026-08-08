"""Bounded cleanup for regenerated user artifacts.

Market-data snapshots, databases, portfolios, configuration and credentials are
deliberately outside this policy. Those records are audit evidence, not cache.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path


def prune_generated_artifacts(
    root: Path,
    *,
    report_days: int = 180,
    diagnostic_days: int = 30,
    update_days: int = 30,
    now: datetime | None = None,
) -> tuple[Path, ...]:
    """Remove only old, reproducible files from explicitly bounded directories."""

    if min(report_days, diagnostic_days, update_days) < 1:
        raise ValueError("retention days must be positive")
    effective_now = now or datetime.now(UTC)
    policies = (
        (root / "reports", report_days),
        (root / "diagnostics", diagnostic_days),
        (root / "updates", update_days),
    )
    removed: list[Path] = []
    resolved_root = root.resolve()
    for directory, days in policies:
        if not directory.exists():
            continue
        cutoff = effective_now - timedelta(days=days)
        for candidate in directory.rglob("*"):
            if not candidate.is_file() or candidate.is_symlink():
                continue
            resolved = candidate.resolve()
            try:
                resolved.relative_to(resolved_root)
            except ValueError as error:  # pragma: no cover - defensive boundary
                raise RuntimeError(f"refusing retention outside {resolved_root}") from error
            modified = datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC)
            if modified < cutoff:
                candidate.unlink()
                removed.append(candidate)
    return tuple(removed)
