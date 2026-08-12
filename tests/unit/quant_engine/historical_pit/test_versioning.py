"""ROUND 7: dataset versioning and certification invalidation tests."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from personal_alpha_terminal.quant_engine.historical_pit.versioning import (
    HistoricalDatasetVersionRegistry,
    build_version,
    certification_is_current,
    version_hashes,
)
from personal_alpha_terminal.quant_engine.research_dataset import (
    certify_research_package,
)
from tests.unit.quant_engine.historical_pit.fixtures import build_certified_package


def test_version_bundle_contains_five_hashes() -> None:
    package = build_certified_package()
    manifest = certify_research_package(package)
    hashes = version_hashes(package, manifest)
    assert hashes["research_data_version"].startswith("research-data-")
    assert hashes["snapshot_hash"] == manifest.content_hash
    assert hashes["security_master_hash"]
    assert hashes["corporate_action_hash"]
    assert hashes["universe_hash"]
    assert len(set(hashes.values())) == 5  # five distinct inputs


def test_any_historical_input_change_invalidates_old_certification() -> None:
    package = build_certified_package()
    manifest = certify_research_package(package)
    first = build_version(package, manifest, published_at=datetime(2024, 6, 2, tzinfo=UTC))
    # Add a price row -> snapshot changes; change a security -> master changes.
    changed_security = replace(
        package.securities[0],
        company_name="Renamed Company",
    )
    changed_package = replace(package, securities=(changed_security, *package.securities[1:]))
    changed_manifest = certify_research_package(changed_package)
    second = build_version(
        changed_package, changed_manifest, published_at=datetime(2024, 6, 3, tzinfo=UTC)
    )

    root = Path(".codex-temp/r7-version-registry")
    if root.exists():
        import shutil

        shutil.rmtree(root)
    registry = HistoricalDatasetVersionRegistry(root)
    registry.publish(first)
    registry.publish(second)

    latest = registry.latest()
    assert latest is not None
    assert latest.research_data_version == second.research_data_version
    # The old certification is superseded.
    old = next(
        item
        for item in registry.load_all()
        if item.research_data_version == first.research_data_version
    )
    assert old.superseded_by == second.research_data_version
    assert old.is_current is False
    # certification_is_current is fail-closed for any hash change.
    assert certification_is_current(latest, second) is True
    assert certification_is_current(latest, first) is False


def test_certification_is_current_fails_closed_without_latest() -> None:
    package = build_certified_package()
    manifest = certify_research_package(package)
    version = build_version(package, manifest)
    assert certification_is_current(None, version) is False
