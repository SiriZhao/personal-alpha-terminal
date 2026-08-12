"""Bounded cleanup for regenerated user artifacts.

Market-data snapshots, databases, portfolios, configuration and credentials are
deliberately outside this policy. Those records are audit evidence, not cache.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class RuntimeArtifactPolicy:
    """Declarative retention policy for one runtime evidence area.

    ``retention_days=None`` means the area is CRITICAL and must never be pruned
    automatically. Only DAILY_REPRODUCIBILITY and DIAGNOSTIC areas are eligible
    for cleanup.
    """

    relative_path: Path
    category: str
    retention_days: int | None


RUNTIME_ARTIFACT_POLICY: tuple[RuntimeArtifactPolicy, ...] = (
    RuntimeArtifactPolicy(Path("reports/daily-runs"), "DAILY_REPRODUCIBILITY", 180),
    RuntimeArtifactPolicy(Path("reports/data-snapshots"), "DAILY_REPRODUCIBILITY", 180),
    RuntimeArtifactPolicy(Path("reports/research-runs"), "DAILY_REPRODUCIBILITY", 180),
    RuntimeArtifactPolicy(Path("var/logs"), "DIAGNOSTIC", 30),
    RuntimeArtifactPolicy(Path("diagnostics"), "DIAGNOSTIC", 30),
    RuntimeArtifactPolicy(Path("updates"), "DIAGNOSTIC", 30),
    RuntimeArtifactPolicy(Path("data/cache"), "CACHE", None),
    RuntimeArtifactPolicy(Path("var/personal_alpha.db"), "CRITICAL", None),
    RuntimeArtifactPolicy(Path("var/operational"), "CRITICAL", None),
    RuntimeArtifactPolicy(Path("var/research-data"), "CRITICAL", None),
    RuntimeArtifactPolicy(Path("var/backups"), "CRITICAL", None),
    RuntimeArtifactPolicy(Path("artifacts"), "CRITICAL", None),
    RuntimeArtifactPolicy(Path("reports/validation-artifacts"), "CRITICAL", None),
)


def runtime_artifact_status(
    root: Path,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, object], ...]:
    """Inventory every governed runtime evidence area without deleting anything."""

    resolved_root = root.resolve()
    effective_now = now or datetime.now(UTC)
    rows: list[dict[str, object]] = []
    for policy in RUNTIME_ARTIFACT_POLICY:
        directory = (resolved_root / policy.relative_path).resolve()
        try:
            directory.relative_to(resolved_root)
        except ValueError as error:  # pragma: no cover - defensive boundary
            raise RuntimeError(f"retention path escapes root: {directory}") from error
        files = (
            tuple(
                candidate
                for candidate in directory.rglob("*")
                if candidate.is_file() and not candidate.is_symlink()
            )
            if directory.exists()
            else ()
        )
        total_bytes = sum(candidate.stat().st_size for candidate in files)
        ages_days: list[int] = []
        for candidate in files:
            modified = datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC)
            ages_days.append(max(0, int((effective_now - modified).total_seconds() // 86400)))
        rows.append(
            {
                "area": policy.relative_path.as_posix(),
                "category": policy.category,
                "retention_days": policy.retention_days,
                "files": len(files),
                "bytes": total_bytes,
                "oldest_days": max(ages_days) if ages_days else 0,
                "eligible_for_cleanup": policy.retention_days is not None,
            }
        )
    return tuple(rows)


def plan_runtime_cleanup(
    root: Path,
    *,
    now: datetime | None = None,
    dry_run: bool = True,
) -> tuple[Path, ...]:
    """Return files that would be removed under the declared policy.

    ``dry_run=True`` (default) never mutates the filesystem. Critical areas and
    CACHE areas are never eligible.
    """

    resolved_root = root.resolve()
    effective_now = now or datetime.now(UTC)
    candidates: list[Path] = []
    for policy in RUNTIME_ARTIFACT_POLICY:
        if policy.retention_days is None:
            continue
        directory = (resolved_root / policy.relative_path).resolve()
        try:
            directory.relative_to(resolved_root)
        except ValueError as error:  # pragma: no cover - defensive boundary
            raise RuntimeError(f"retention path escapes root: {directory}") from error
        if not directory.exists():
            continue
        cutoff = effective_now - timedelta(days=policy.retention_days)
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
                candidates.append(resolved)
    planned = tuple(sorted(candidates))
    if dry_run:
        return planned
    for candidate in planned:
        candidate.unlink()
    return planned


def apply_runtime_cleanup(root: Path, *, now: datetime | None = None) -> tuple[Path, ...]:
    """Explicitly apply the declared cleanup policy (never critical evidence)."""

    return plan_runtime_cleanup(root, now=now, dry_run=False)
