"""ROUND74 certified-data import and fail-closed certification tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from personal_alpha_terminal.research.certified_data import (
    CertifiedDataPackage,
    CertifiedEvidenceClass,
    EvidenceCoverageDeclaration,
    ImmutableDataRecord,
    ReturnSemanticsContract,
    build_procurement_manifest,
    certify_data_package,
    current_data_certification,
    parse_certified_data_package,
    validate_return_semantics,
)
from personal_alpha_terminal.research.data_evidence import EvidenceStatus

NOW = datetime(2024, 1, 3, 20, tzinfo=UTC)


def _record(
    evidence_class: CertifiedEvidenceClass,
    *,
    source_identifier: str | None = None,
    vintage: str = "v1",
    content_hash: str = "content-a",
    available_at: datetime = NOW,
) -> ImmutableDataRecord:
    return ImmutableDataRecord(
        evidence_class=evidence_class,
        permanent_security_id=(
            None
            if evidence_class is CertifiedEvidenceClass.NEWS_EVENTS
            else "PERM-1"
        ),
        symbol_at_time=(
            "OLD" if evidence_class in {
                CertifiedEvidenceClass.PERMANENT_SECURITY_IDENTITY,
                CertifiedEvidenceClass.SYMBOL_HISTORY,
                CertifiedEvidenceClass.RAW_PIT_OHLCV,
                CertifiedEvidenceClass.EXECUTABLE_OPENS,
            } else None
        ),
        effective_at=NOW - timedelta(days=1),
        observed_at=NOW - timedelta(hours=2),
        published_at=(NOW - timedelta(hours=3)) if evidence_class in {
            CertifiedEvidenceClass.FUNDAMENTALS,
            CertifiedEvidenceClass.FILINGS,
            CertifiedEvidenceClass.NEWS_EVENTS,
        } else None,
        available_at=available_at,
        ingested_at=max(NOW, available_at),
        vintage=vintage,
        source="fixture-source",
        provider="fixture-provider",
        source_identifier=source_identifier or evidence_class.value,
        content_hash=content_hash,
        adjustment_semantics=(
            "RAW"
            if evidence_class is CertifiedEvidenceClass.RAW_PIT_OHLCV
            else "NOT_APPLICABLE"
        ),
        payload={"fixture": True},
    )


def _coverage(
    evidence_class: CertifiedEvidenceClass,
    *,
    supplied: int = 1,
) -> EvidenceCoverageDeclaration:
    return EvidenceCoverageDeclaration(
        evidence_class=evidence_class,
        source="fixture-source",
        provider="fixture-provider",
        coverage_start=date(2020, 1, 1),
        coverage_end=date(2023, 12, 31),
        security_scope_hash="scope-hash",
        source_contract_hash="contract-hash",
        expected_record_count=1,
        supplied_record_count=supplied,
        declared_complete=True,
    )


def _complete_package() -> CertifiedDataPackage:
    return CertifiedDataPackage(
        schema_version="ROUND74-CERTIFIED-DATA-IMPORT-v1",
        dataset_id="fixture-data",
        dataset_vintage="2024-01-03T20:00:00+00:00",
        created_at=NOW,
        coverage=tuple(_coverage(item) for item in CertifiedEvidenceClass),
        records=tuple(_record(item) for item in CertifiedEvidenceClass),
    )


def test_current_certification_is_explicitly_blocked_without_bound_import() -> None:
    result = current_data_certification()
    assert result.overall_status is EvidenceStatus.BLOCKED_DATA_QUALITY
    assert not result.promotion_allowed
    assert len(result.classes) == 12
    assert all("NO_BOUND_IMMUTABLE_IMPORT_PACKAGE" in item.blockers for item in result.classes)


def test_complete_versioned_fixture_package_passes_software_contract_only() -> None:
    result = certify_data_package(_complete_package())
    assert result.overall_status is EvidenceStatus.PASS
    assert result.promotion_allowed
    assert all(item.status is EvidenceStatus.PASS for item in result.classes)


def test_missing_coverage_stays_blocked_and_is_not_neutral_filled() -> None:
    package = _complete_package()
    incomplete = CertifiedDataPackage(
        schema_version=package.schema_version,
        dataset_id=package.dataset_id,
        dataset_vintage=package.dataset_vintage,
        created_at=package.created_at,
        coverage=tuple(
            item
            for item in package.coverage
            if item.evidence_class is not CertifiedEvidenceClass.DELISTINGS_AND_RETURNS
        ),
        records=tuple(
            item
            for item in package.records
            if item.evidence_class is not CertifiedEvidenceClass.DELISTINGS_AND_RETURNS
        ),
    )
    result = certify_data_package(incomplete)
    row = next(
        item
        for item in result.classes
        if item.evidence_class is CertifiedEvidenceClass.DELISTINGS_AND_RETURNS
    )
    assert row.status is EvidenceStatus.BLOCKED_SURVIVORSHIP
    assert "MISSING_COVERAGE_DECLARATION" in row.blockers
    assert not result.promotion_allowed


def test_same_vintage_different_content_is_rejected_as_overwrite_conflict() -> None:
    package = _complete_package()
    original = package.records[0]
    changed = _record(
        original.evidence_class,
        source_identifier=original.source_identifier,
        vintage=original.vintage,
        content_hash="content-b",
    )
    duplicate = CertifiedDataPackage(
        schema_version=package.schema_version,
        dataset_id=package.dataset_id,
        dataset_vintage=package.dataset_vintage,
        created_at=package.created_at,
        coverage=package.coverage,
        records=package.records + (changed,),
    )
    result = certify_data_package(duplicate)
    assert "permanent_security_identity:IMMUTABLE_VINTAGE_OVERWRITE_CONFLICT" in result.blockers


def test_future_available_observation_is_not_visible_at_historical_decision() -> None:
    future = _record(
        CertifiedEvidenceClass.FUNDAMENTALS,
        available_at=NOW + timedelta(minutes=1),
    )
    assert not future.visible_at(NOW)


def test_parser_requires_timezone_aware_critical_timestamps() -> None:
    document = _complete_package().document()
    records = document["records"]
    assert isinstance(records, list)
    first = records[0]
    assert isinstance(first, dict)
    first["available_at"] = "2024-01-03T20:00:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_certified_data_package(document)


def test_return_contract_rejects_double_adjustment_and_benchmark_mismatch() -> None:
    blockers = validate_return_semantics(
        ReturnSemanticsContract(
            asset_price_semantics="POINT_IN_TIME_TOTAL_RETURN",
            corporate_actions_applied_separately=True,
            benchmark_return_semantics="RAW",
            benchmark_corporate_actions_applied_separately=False,
        )
    )
    assert "ASSET_DOUBLE_CORPORATE_ACTION_ADJUSTMENT" in blockers
    assert "RAW_BENCHMARK_REQUIRES_EXPLICIT_CORPORATE_ACTION_RECONSTRUCTION" in blockers
    assert "BENCHMARK_RETURN_SEMANTICS_MISMATCH" in blockers


def test_procurement_manifest_lists_all_required_evidence_classes_and_unbound_ranges() -> None:
    manifest = build_procurement_manifest(generated_at=NOW)
    requirements = manifest["requirements"]
    assert isinstance(requirements, list)
    assert len(requirements) == 12
    assert all(item["date_range"]["start"] is None for item in requirements)
