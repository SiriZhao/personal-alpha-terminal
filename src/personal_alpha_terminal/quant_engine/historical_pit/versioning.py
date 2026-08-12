"""ROUND 7: research dataset versioning and certification invalidation.

A research certification is only valid for one immutable input version.  The
version bundle binds:

- research_data_version
- snapshot_hash
- security_master_hash
- corporate_action_hash
- universe_hash

Any historical input change produces a new version and automatically supersedes
(invalidates) all older certifications.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.quant_engine.research_data import ResearchDatasetState
from personal_alpha_terminal.quant_engine.research_dataset import (
    ResearchDatasetManifestV2,
    ResearchDatasetPackage,
)


@dataclass(frozen=True, slots=True)
class ResearchDatasetVersion:
    research_data_version: str
    snapshot_hash: str
    security_master_hash: str
    corporate_action_hash: str
    universe_hash: str
    certification_state: ResearchDatasetState
    providers: tuple[str, ...]
    published_at: datetime
    superseded_by: str | None = None
    superseded_reason: str | None = None

    def __post_init__(self) -> None:
        if self.published_at.tzinfo is None:
            raise ValueError("dataset version published_at must be timezone-aware")
        if not self.research_data_version.strip():
            raise ValueError("research_data_version is required")

    @property
    def is_current(self) -> bool:
        return self.superseded_by is None

    def document(self) -> dict[str, object]:
        return {
            "research_data_version": self.research_data_version,
            "snapshot_hash": self.snapshot_hash,
            "security_master_hash": self.security_master_hash,
            "corporate_action_hash": self.corporate_action_hash,
            "universe_hash": self.universe_hash,
            "certification_state": self.certification_state.value,
            "providers": sorted(self.providers),
            "published_at": self.published_at.isoformat(),
            "superseded_by": self.superseded_by,
            "superseded_reason": self.superseded_reason,
        }


def version_hashes(
    package: ResearchDatasetPackage,
    manifest: ResearchDatasetManifestV2,
) -> dict[str, str]:
    """Derive the five version hashes for a certified raw package + manifest."""
    security_master_hash = fingerprint(
        tuple(
            sorted(
                (
                    item.permanent_security_id,
                    item.ticker,
                    item.ticker_valid_from.isoformat(),
                    item.ticker_valid_to.isoformat() if item.ticker_valid_to else None,
                    item.listing_date.isoformat() if item.listing_date else None,
                    item.delisting_date.isoformat() if item.delisting_date else None,
                )
                for item in package.securities
            )
        )
    )
    corporate_action_hash = fingerprint(
        tuple(
            sorted(
                (
                    item.permanent_security_id,
                    item.action_type,
                    item.effective_date.isoformat(),
                    item.announcement_date.isoformat() if item.announcement_date else None,
                    item.available_at.isoformat(),
                    item.revision_id or "",
                )
                for item in package.corporate_actions
            )
        )
    )
    universe_hash = fingerprint(
        tuple(
            sorted(
                (
                    item.permanent_security_id,
                    item.universe_id,
                    item.effective_from.isoformat(),
                    item.effective_to.isoformat() if item.effective_to else None,
                )
                for item in package.memberships
            )
        )
    )
    snapshot_hash = manifest.content_hash
    research_data_version = f"research-data-{snapshot_hash[:24]}"
    return {
        "research_data_version": research_data_version,
        "snapshot_hash": snapshot_hash,
        "security_master_hash": security_master_hash,
        "corporate_action_hash": corporate_action_hash,
        "universe_hash": universe_hash,
    }


def build_version(
    package: ResearchDatasetPackage,
    manifest: ResearchDatasetManifestV2,
    *,
    published_at: datetime | None = None,
) -> ResearchDatasetVersion:
    hashes = version_hashes(package, manifest)
    return ResearchDatasetVersion(
        research_data_version=hashes["research_data_version"],
        snapshot_hash=hashes["snapshot_hash"],
        security_master_hash=hashes["security_master_hash"],
        corporate_action_hash=hashes["corporate_action_hash"],
        universe_hash=hashes["universe_hash"],
        certification_state=manifest.certification_state,
        providers=(package.provider,),
        published_at=published_at or datetime.now(UTC),
    )


class HistoricalDatasetVersionRegistry:
    """Immutable file registry; publishing a new version invalidates older ones."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def publish(self, version: ResearchDatasetVersion) -> ResearchDatasetVersion:
        existing = self.load_all()
        if existing:
            for older in existing:
                if older.is_current:
                    older = ResearchDatasetVersion(
                        research_data_version=older.research_data_version,
                        snapshot_hash=older.snapshot_hash,
                        security_master_hash=older.security_master_hash,
                        corporate_action_hash=older.corporate_action_hash,
                        universe_hash=older.universe_hash,
                        certification_state=older.certification_state,
                        providers=older.providers,
                        published_at=older.published_at,
                        superseded_by=version.research_data_version,
                        superseded_reason=(
                            "historical input changed; old certification invalidated"
                        ),
                    )
                    self._write(older, overwrite=True)
        self._write(version)
        return version

    def latest(self) -> ResearchDatasetVersion | None:
        current = [
            item
            for item in self.load_all()
            if item.is_current and item.certification_state is ResearchDatasetState.CERTIFIED
        ]
        if not current:
            return None
        return max(current, key=lambda item: item.published_at)

    def load_all(self) -> tuple[ResearchDatasetVersion, ...]:
        if not self.root.exists():
            return ()
        versions: list[ResearchDatasetVersion] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                versions.append(_version_from_document(payload))
            except (OSError, KeyError, TypeError, ValueError):
                continue
        return tuple(versions)

    def _write(self, version: ResearchDatasetVersion, *, overwrite: bool = False) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{version.research_data_version}.json"
        rendered = (
            json.dumps(version.document(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        if target.exists() and target.read_text(encoding="utf-8") != rendered:
            if not overwrite:
                raise ValueError(f"dataset version conflict: {target}")
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(target)


def certification_is_current(
    latest: ResearchDatasetVersion | None,
    candidate: ResearchDatasetVersion,
) -> bool:
    """Fail-closed: any historical input change invalidates an old certification.

    A candidate matches the latest only when every input hash is identical.  A
    None latest (no certified version) means the candidate cannot be considered
    current until it is published as the latest.
    """
    if latest is None:
        return False
    return (
        latest.snapshot_hash == candidate.snapshot_hash
        and latest.security_master_hash == candidate.security_master_hash
        and latest.corporate_action_hash == candidate.corporate_action_hash
        and latest.universe_hash == candidate.universe_hash
    )


def _version_from_document(payload: dict[str, Any]) -> ResearchDatasetVersion:
    return ResearchDatasetVersion(
        research_data_version=str(payload["research_data_version"]),
        snapshot_hash=str(payload["snapshot_hash"]),
        security_master_hash=str(payload["security_master_hash"]),
        corporate_action_hash=str(payload["corporate_action_hash"]),
        universe_hash=str(payload["universe_hash"]),
        certification_state=ResearchDatasetState(str(payload["certification_state"])),
        providers=tuple(str(item) for item in cast(list[Any], payload["providers"])),
        published_at=datetime.fromisoformat(str(payload["published_at"])),
        superseded_by=(
            str(payload["superseded_by"]) if payload.get("superseded_by") else None
        ),
        superseded_reason=(
            str(payload["superseded_reason"])
            if payload.get("superseded_reason")
            else None
        ),
    )
