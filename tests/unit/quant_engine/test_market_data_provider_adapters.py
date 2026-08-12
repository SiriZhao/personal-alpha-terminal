import csv
from dataclasses import replace
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

from personal_alpha_terminal.quant_engine.research_dataset import (
    HistoricalSecurity,
    ResearchDatasetPackage,
    ResearchUseScope,
    SecurityType,
    package_to_import_rows,
)
from personal_alpha_terminal.quant_engine.research_provider_acceptance import (
    ProviderContract,
)
from personal_alpha_terminal.quant_engine.research_provider_adapters import (
    LocalResearchPackageAdapter,
    RawFileEntry,
    build_raw_manifest,
    load_raw_manifest,
    persist_raw_manifest,
    verify_raw_landing_zone,
)


def _package(
    *,
    provider: str = "licensed-provider",
    provider_version: str = "provider-v1",
) -> ResearchDatasetPackage:
    security = HistoricalSecurity(
        "SEC-PERM-1",
        "TICK",
        date(2018, 7, 3),
        None,
        "XNYS",
        date(2018, 7, 3),
        None,
        "UNKNOWN",
        SecurityType.US_EQUITY,
        datetime(2018, 7, 2, tzinfo=UTC),
        "licensed provider",
        provider,
        provider_security_id="PROV-1",
        company_id="COMPANY-1",
    )
    return ResearchDatasetPackage(
        dataset_id="adapter-fixture",
        schema_version="research-package-v1",
        provider=provider,
        source="licensed provider",
        retrieved_at=datetime(2024, 1, 6, tzinfo=UTC),
        as_of=date(2024, 1, 5),
        cutoff=datetime(2024, 1, 6, tzinfo=UTC),
        use_scope=ResearchUseScope.PRODUCTION_RESEARCH,
        securities=(security,),
        memberships=(),
        prices=(),
        corporate_actions=(),
        calendar=(),
        provider_version=provider_version,
        acquisition_id="acq-1",
        license_scope="LOCAL_RESEARCH",
        benchmark_universe_id="BENCHMARK-US",
    )


def _write_package(path: Path, package: ResearchDatasetPackage) -> None:
    rows = package_to_import_rows(package)
    columns = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _contract(provider_version: str = "provider-v1") -> ProviderContract:
    return ProviderContract(
        provider_id="licensed-provider",
        provider_version=provider_version,
        provider_security_id_scheme="provider-id",
        permanent_identifiers=True,
        delisting_history=True,
        delisting_returns=True,
        historical_membership=True,
        corporate_actions_pit=True,
        total_return_pit=True,
        benchmark_same_pit=True,
        license_scope="LOCAL_RESEARCH",
        local_research_use_allowed=True,
        derived_research_allowed=True,
        schema_mapping_version="fixture-v1",
        source_identity="signed-provider-manifest",
    )


def test_raw_manifest_hash_is_deterministic_and_persistable(tmp_path: Path) -> None:
    source = tmp_path / "package.csv"
    _write_package(source, _package())
    entry = RawFileEntry(
        path=source.name,
        sha256=sha256(source.read_bytes()).hexdigest(),
        size_bytes=source.stat().st_size,
        role="normalized_package",
    )
    first = build_raw_manifest(
        provider_id="licensed-provider",
        provider_version="provider-v1",
        acquisition_id="acq-1",
        source_identity="signed-provider-manifest",
        retrieved_at=datetime(2024, 1, 6, tzinfo=UTC),
        license_scope="LOCAL_RESEARCH",
        local_research_use_allowed=True,
        derived_research_allowed=True,
        files=(entry,),
        coverage_start=date(2018, 7, 3),
        coverage_end=date(2024, 1, 5),
        security_count=1,
        price_count=0,
    )
    second = build_raw_manifest(
        provider_id="licensed-provider",
        provider_version="provider-v1",
        acquisition_id="acq-1",
        source_identity="signed-provider-manifest",
        retrieved_at=datetime(2024, 1, 6, tzinfo=UTC),
        license_scope="LOCAL_RESEARCH",
        local_research_use_allowed=True,
        derived_research_allowed=True,
        files=(entry,),
        coverage_start=date(2018, 7, 3),
        coverage_end=date(2024, 1, 5),
        security_count=1,
        price_count=0,
    )
    assert first.manifest_hash == second.manifest_hash
    assert first.content_hash == second.content_hash
    path = persist_raw_manifest(first, tmp_path / "landing")
    assert path.exists()
    assert load_raw_manifest(tmp_path / "landing").content_hash == first.content_hash


def test_raw_landing_zone_rejects_corrupted_payload(tmp_path: Path) -> None:
    source = tmp_path / "package.csv"
    _write_package(source, _package())
    entry = RawFileEntry(
        path=source.name,
        sha256=sha256(source.read_bytes()).hexdigest(),
        size_bytes=source.stat().st_size,
        role="normalized_package",
    )
    manifest = build_raw_manifest(
        provider_id="licensed-provider",
        provider_version="provider-v1",
        acquisition_id="acq-1",
        source_identity="signed-provider-manifest",
        retrieved_at=datetime(2024, 1, 6, tzinfo=UTC),
        license_scope="LOCAL_RESEARCH",
        local_research_use_allowed=True,
        derived_research_allowed=True,
        files=(entry,),
    )
    root = tmp_path / "landing"
    root.mkdir()
    source.replace(root / source.name)
    persist_raw_manifest(manifest, root)
    (root / source.name).write_text("corrupted", encoding="utf-8")
    verification = verify_raw_landing_zone(root)
    assert verification.ok is False
    assert any("CHECKSUM_MISMATCH" in item for item in verification.blockers)


def test_duplicate_redownload_reuses_identical_raw_identity(tmp_path: Path) -> None:
    source = tmp_path / "package.csv"
    _write_package(source, _package())
    entry = RawFileEntry(
        path=source.name,
        sha256=sha256(source.read_bytes()).hexdigest(),
        size_bytes=source.stat().st_size,
        role="normalized_package",
    )
    root = tmp_path / "landing"
    root.mkdir()
    source.replace(root / source.name)

    first = build_raw_manifest(
        provider_id="licensed-provider",
        provider_version="provider-v1",
        acquisition_id="acq-1",
        source_identity="signed-provider-manifest",
        retrieved_at=datetime(2024, 1, 6, tzinfo=UTC),
        license_scope="LOCAL_RESEARCH",
        local_research_use_allowed=True,
        derived_research_allowed=True,
        files=(entry,),
        coverage_start=date(2018, 7, 3),
        coverage_end=date(2024, 1, 5),
        security_count=1,
        price_count=0,
    )
    second = build_raw_manifest(
        provider_id="licensed-provider",
        provider_version="provider-v1",
        acquisition_id="acq-1",
        source_identity="signed-provider-manifest",
        retrieved_at=datetime(2024, 1, 6, tzinfo=UTC),
        license_scope="LOCAL_RESEARCH",
        local_research_use_allowed=True,
        derived_research_allowed=True,
        files=(entry,),
        coverage_start=date(2018, 7, 3),
        coverage_end=date(2024, 1, 5),
        security_count=1,
        price_count=0,
    )

    persist_raw_manifest(first, root)
    persist_raw_manifest(second, root)
    assert second.content_hash == first.content_hash
    assert load_raw_manifest(root).content_hash == first.content_hash
    verification = verify_raw_landing_zone(root)
    assert verification.ok is True
    assert verification.blockers == ()


def test_provider_mapping_is_deterministic_and_version_change_rejected(
    tmp_path: Path,
) -> None:
    package = _package()
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    _write_package(first_path, package)
    _write_package(second_path, package)
    adapter = LocalResearchPackageAdapter(_contract(), "provider-v1")
    first = adapter.load(first_path)
    second = adapter.load(second_path)
    assert first.content_hash == second.content_hash

    changed = _package(provider_version="provider-v2")
    changed_path = tmp_path / "changed.csv"
    _write_package(changed_path, changed)
    try:
        adapter.load(changed_path)
    except ValueError as error:
        assert "does not match the adapter contract" in str(error)
    else:
        raise AssertionError("provider version mismatch was accepted")


def test_permanent_id_survives_ticker_change_through_provider_package(
    tmp_path: Path,
) -> None:
    package = _package()
    old = package.securities[0]
    new = HistoricalSecurity(
        "SEC-PERM-1",
        "NEWTICK",
        date(2024, 1, 5),
        None,
        old.exchange,
        old.listing_date,
        old.delisting_date,
        old.delisting_reason,
        old.security_type,
        old.available_at,
        old.source,
        old.provider,
        cusip=old.cusip,
        figi=old.figi,
        provider_security_id=old.provider_security_id,
        company_id=old.company_id,
        company_name=old.company_name,
    )
    changed = replace(package, securities=(old, new))
    assert {item.permanent_security_id for item in changed.securities} == {"SEC-PERM-1"}
    assert {item.ticker for item in changed.securities} == {"TICK", "NEWTICK"}
    assert changed.content_hash != package.content_hash


def test_raw_manifest_provider_version_change_changes_identity(tmp_path: Path) -> None:
    source = tmp_path / "package.csv"
    _write_package(source, _package())
    entry = RawFileEntry(
        path=source.name,
        sha256=sha256(source.read_bytes()).hexdigest(),
        size_bytes=source.stat().st_size,
        role="normalized_package",
    )
    kwargs = {
        "provider_id": "licensed-provider",
        "acquisition_id": "acq-1",
        "source_identity": "signed-provider-manifest",
        "retrieved_at": datetime(2024, 1, 6, tzinfo=UTC),
        "license_scope": "LOCAL_RESEARCH",
        "local_research_use_allowed": True,
        "derived_research_allowed": True,
        "files": (entry,),
    }
    first = build_raw_manifest(provider_version="provider-v1", **kwargs)
    second = build_raw_manifest(provider_version="provider-v2", **kwargs)
    assert first.content_hash != second.content_hash
    assert first.manifest_hash != second.manifest_hash
