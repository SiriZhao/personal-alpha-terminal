"""Provider-neutral local research package adapters and raw landing zones.

This module is the boundary between a licensed provider's raw local payload and
the existing ``ResearchDatasetPackage`` contract.  It never certifies a package;
provider acceptance remains the responsibility of
``accept_research_provider``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import cast

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.quant_engine.research_dataset import (
    ResearchDatasetPackage,
    ResearchUseScope,
    import_research_package,
)
from personal_alpha_terminal.quant_engine.research_provider_acceptance import (
    ProviderContract,
)


@dataclass(frozen=True, slots=True)
class RawFileEntry:
    path: str
    sha256: str
    size_bytes: int
    role: str

    def __post_init__(self) -> None:
        if not self.path.strip() or not self.role.strip():
            raise ValueError("raw file entry identity is incomplete")
        if not self.sha256:
            raise ValueError("raw file entry checksum is missing")
        if self.size_bytes < 0:
            raise ValueError("raw file size cannot be negative")

    def document(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(json.dumps(asdict(self))))


@dataclass(frozen=True, slots=True)
class RawAcquisitionManifest:
    schema_version: str
    provider_id: str
    provider_version: str
    acquisition_id: str
    source_identity: str
    retrieved_at: datetime
    license_scope: str
    local_research_use_allowed: bool
    derived_research_allowed: bool
    files: tuple[RawFileEntry, ...]
    coverage_start: date | None
    coverage_end: date | None
    security_count: int
    price_count: int
    content_hash: str
    manifest_hash: str = ""

    def __post_init__(self) -> None:
        if (
            not self.schema_version.strip()
            or not self.provider_id.strip()
            or not self.provider_version.strip()
            or not self.acquisition_id.strip()
            or not self.source_identity.strip()
        ):
            raise ValueError("raw acquisition manifest identity is incomplete")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("raw acquisition retrieved_at must be timezone-aware")
        if self.security_count < 0 or self.price_count < 0:
            raise ValueError("raw acquisition counts cannot be negative")
        if self.coverage_start is not None and self.coverage_end is not None:
            if self.coverage_end < self.coverage_start:
                raise ValueError("raw acquisition coverage end precedes start")
        if not self.content_hash:
            raise ValueError("raw acquisition content hash is missing")

    def document(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(json.dumps(asdict(self), default=str)))

    def verified(self) -> RawAcquisitionManifest:
        if not self.manifest_hash:
            return self
        material = self.document()
        material.pop("manifest_hash", None)
        if fingerprint(material) != self.manifest_hash:
            raise ValueError("raw acquisition manifest hash mismatch")
        return self


@dataclass(frozen=True, slots=True)
class RawLandingZoneVerification:
    ok: bool
    blockers: tuple[str, ...]


def build_raw_manifest(
    *,
    provider_id: str,
    provider_version: str,
    acquisition_id: str,
    source_identity: str,
    retrieved_at: datetime,
    license_scope: str,
    local_research_use_allowed: bool,
    derived_research_allowed: bool,
    files: tuple[RawFileEntry, ...],
    coverage_start: date | None = None,
    coverage_end: date | None = None,
    security_count: int = 0,
    price_count: int = 0,
) -> RawAcquisitionManifest:
    ordered_files = tuple(sorted(files, key=lambda item: item.path))
    content_hash = fingerprint(
        {
            "provider_version": provider_version,
            "files": tuple(item.document() for item in ordered_files),
        }
    )
    manifest = RawAcquisitionManifest(
        schema_version="market-data-raw-v1",
        provider_id=provider_id,
        provider_version=provider_version,
        acquisition_id=acquisition_id,
        source_identity=source_identity,
        retrieved_at=retrieved_at,
        license_scope=license_scope,
        local_research_use_allowed=local_research_use_allowed,
        derived_research_allowed=derived_research_allowed,
        files=ordered_files,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        security_count=security_count,
        price_count=price_count,
        content_hash=content_hash,
    )
    manifest_hash = fingerprint(
        {
            key: value
            for key, value in manifest.document().items()
            if key != "manifest_hash"
        }
    )
    return replace(manifest, manifest_hash=manifest_hash)


def persist_raw_manifest(manifest: RawAcquisitionManifest, root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / "manifest.json"
    rendered = json.dumps(
        manifest.document(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if target.exists() and target.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite immutable raw manifest: {target}")
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(target)
    return target


def load_raw_manifest(root: Path) -> RawAcquisitionManifest:
    document = cast(
        dict[str, object],
        json.loads((root / "manifest.json").read_text(encoding="utf-8")),
    )
    manifest = RawAcquisitionManifest(
        schema_version=str(document["schema_version"]),
        provider_id=str(document["provider_id"]),
        provider_version=str(document["provider_version"]),
        acquisition_id=str(document["acquisition_id"]),
        source_identity=str(document["source_identity"]),
        retrieved_at=datetime.fromisoformat(str(document["retrieved_at"])),
        license_scope=str(document["license_scope"]),
        local_research_use_allowed=bool(document["local_research_use_allowed"]),
        derived_research_allowed=bool(document["derived_research_allowed"]),
        files=tuple(
            RawFileEntry(
                path=str(item["path"]),
                sha256=str(item["sha256"]),
                size_bytes=int(str(item["size_bytes"])),
                role=str(item["role"]),
            )
            for item in cast(list[dict[str, object]], document["files"])
        ),
        coverage_start=(
            date.fromisoformat(str(document["coverage_start"]))
            if document.get("coverage_start")
            else None
        ),
        coverage_end=(
            date.fromisoformat(str(document["coverage_end"]))
            if document.get("coverage_end")
            else None
        ),
        security_count=int(str(document["security_count"])),
        price_count=int(str(document["price_count"])),
        content_hash=str(document["content_hash"]),
        manifest_hash=str(document.get("manifest_hash") or ""),
    ).verified()
    expected_content_hash = fingerprint(
        {
            "provider_version": manifest.provider_version,
            "files": tuple(item.document() for item in manifest.files),
        }
    )
    if expected_content_hash != manifest.content_hash:
        raise ValueError("raw acquisition content hash mismatch")
    return manifest


def verify_raw_landing_zone(root: Path) -> RawLandingZoneVerification:
    blockers: list[str] = []
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return RawLandingZoneVerification(False, ("RAW_LANDING_MANIFEST_MISSING",))
    try:
        manifest = load_raw_manifest(root)
    except (OSError, ValueError, KeyError) as error:
        return RawLandingZoneVerification(
            False,
            (f"RAW_LANDING_MANIFEST_INVALID:{type(error).__name__}",),
        )
    for entry in manifest.files:
        target = (root / entry.path).resolve()
        root_resolved = root.resolve()
        if root_resolved not in target.parents:
            blockers.append(f"RAW_FILE_OUTSIDE_LANDING_ZONE:{entry.path}")
            continue
        if not target.exists():
            blockers.append(f"RAW_FILE_MISSING:{entry.path}")
            continue
        payload = target.read_bytes()
        if len(payload) != entry.size_bytes:
            blockers.append(f"RAW_FILE_SIZE_MISMATCH:{entry.path}")
        if sha256(payload).hexdigest() != entry.sha256:
            blockers.append(f"RAW_FILE_CHECKSUM_MISMATCH:{entry.path}")
    if blockers:
        return RawLandingZoneVerification(False, tuple(dict.fromkeys(blockers)))
    return RawLandingZoneVerification(True, ())


class LocalResearchPackageAdapter:
    """Load a normalized provider package while enforcing provider identity.

    The adapter intentionally accepts only ``PRODUCTION_RESEARCH`` packages.
    Vendor-specific conversion is expected to happen before this adapter, in a
    licensed local acquisition script, and to preserve the raw landing zone.
    """

    def __init__(self, contract: ProviderContract, provider_version: str) -> None:
        self.provider_id = contract.provider_id
        self.provider_version = provider_version
        self.contract = contract

    def load(self, source: Path) -> ResearchDatasetPackage:
        package = import_research_package(source)
        if package.provider != self.provider_id:
            raise ValueError(
                f"provider package identity mismatch: {package.provider} != {self.provider_id}"
            )
        if package.provider_version != self.provider_version:
            raise ValueError(
                "provider package version does not match the adapter contract"
            )
        if package.use_scope is not ResearchUseScope.PRODUCTION_RESEARCH:
            raise ValueError("TEST_FIXTURE package is not accepted by the research adapter")
        return package


def load_licensed_raw_package(
    *,
    root: Path,
    package_source: Path,
    adapter: LocalResearchPackageAdapter,
) -> tuple[RawLandingZoneVerification, ResearchDatasetPackage]:
    verification = verify_raw_landing_zone(root)
    if not verification.ok:
        raise ValueError(
            "raw landing zone verification failed: "
            + "; ".join(verification.blockers)
        )
    return verification, adapter.load(package_source)
