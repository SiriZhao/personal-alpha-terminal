"""ROUND80 Part 2 evidence, snapshot, and no-look-ahead contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.data.authority import (
    AuthorityEvidenceRepository,
    BenchmarkEvidence,
    DataDomain,
    DataQualityStatus,
    ExecutableNextSessionOpen,
    HistoricalIndexConstituent,
    HistoricalUniverseQualityStatus,
    ImmutableRawFetchEvidence,
    PITUniverseCandidate,
    ProviderConflictResolution,
    ProviderValueConflict,
    ReturnSemantics,
    TotalReturnObservation,
    TotalReturnReconciliationStatus,
    audit_benchmark_alignment,
    audit_executable_next_session_open,
    build_pit_investable_universe,
    create_dataset_snapshot,
    declared_provider_health,
    default_provider_registry,
    evaluate_production_authority_gate,
    index_constituents_visible_at,
    macro_vintages_visible_at,
    reconcile_total_return,
)
from personal_alpha_terminal.data.authority.research_foundation import MacroVintageObservation

NOW = datetime(2024, 2, 2, 21, 30, tzinfo=UTC)


def _candidate(
    security_id: str,
    *,
    known_at: datetime = NOW,
    identity: bool = True,
    membership: bool = True,
    lifecycle: bool = True,
    delisting: bool = True,
    tradable: bool = True,
) -> PITUniverseCandidate:
    return PITUniverseCandidate(
        security_id=security_id,
        session_date=date(2024, 2, 2),
        known_at=known_at,
        security_type="COMMON",
        listing_date=date(2020, 1, 1),
        delisting_date=None,
        active=True,
        tradable=tradable,
        identity_resolved=identity,
        raw_price=100.0,
        average_dollar_volume=20_000_000.0,
        observed_sessions=500,
        lifecycle_evidence_complete=lifecycle,
        permanent_identifier_evidence_complete=identity,
        historical_membership_evidence_complete=membership,
        delisting_return_evidence_complete=delisting,
        source="authoritative-import",
    )


def test_historical_universe_is_pit_visible_and_never_silently_survivorship_safe() -> None:
    universe = build_pit_investable_universe(
        (
            _candidate("SEC-A"),
            _candidate("SEC-B", membership=False),
            _candidate("SEC-FUTURE", known_at=NOW + timedelta(minutes=1)),
        ),
        decision_timestamp=NOW,
        minimum_price=5.0,
        minimum_average_dollar_volume=10_000_000.0,
        minimum_history_sessions=252,
    )
    assert universe.members == ("SEC-A",)
    assert universe.quality_status is HistoricalUniverseQualityStatus.PARTIAL
    assert "HISTORICAL_UNIVERSE_MEMBERSHIP_INCOMPLETE" in universe.blockers
    assert "FUTURE_UNIVERSE_EVIDENCE" in universe.exclusions["SEC-FUTURE"]


def test_constituents_and_macro_vintages_obey_known_at_boundary() -> None:
    record = HistoricalIndexConstituent(
        index_id="SP500",
        security_id="SEC-A",
        effective_from=date(2024, 2, 1),
        effective_to=None,
        announcement_time=NOW,
        known_at=NOW,
        source="licensed-import",
        source_record_id="SP500-1",
        confidence=0.95,
    )
    assert index_constituents_visible_at(
        (record,), index_id="SP500", session_date=date(2024, 2, 2), decision_timestamp=NOW
    ) == ("SEC-A",)
    assert index_constituents_visible_at(
        (record,),
        index_id="SP500",
        session_date=date(2024, 2, 2),
        decision_timestamp=NOW - timedelta(seconds=1),
    ) == ()
    first = MacroVintageObservation(
        "DFF", date(2024, 1, 31), 5.0, date(2024, 2, 1), NOW, NOW, "alfred", NOW
    )
    revised = MacroVintageObservation(
        "DFF", date(2024, 1, 31), 5.25, date(2024, 2, 3), NOW + timedelta(days=1),
        NOW + timedelta(days=1), "alfred", NOW + timedelta(days=1)
    )
    assert macro_vintages_visible_at((first, revised), decision_timestamp=NOW) == (first,)


def test_total_return_reconciliation_and_benchmark_semantics_fail_closed() -> None:
    primary = (
        TotalReturnObservation(
            date(2024, 2, 1),
            100.0,
            NOW,
            "internal",
            ReturnSemantics.POINT_IN_TIME_TOTAL_RETURN,
        ),
        TotalReturnObservation(
            date(2024, 2, 2),
            101.0,
            NOW,
            "internal",
            ReturnSemantics.POINT_IN_TIME_TOTAL_RETURN,
        ),
    )
    secondary = (
        TotalReturnObservation(
            date(2024, 2, 1),
            100.0,
            NOW,
            "yahoo",
            ReturnSemantics.PROVIDER_ADJUSTED_UNVERIFIED,
        ),
        TotalReturnObservation(
            date(2024, 2, 2),
            104.0,
            NOW,
            "yahoo",
            ReturnSemantics.PROVIDER_ADJUSTED_UNVERIFIED,
        ),
    )
    reconciliation = reconcile_total_return(
        security_id="SEC-A", primary=primary, secondary=secondary, decision_timestamp=NOW
    )
    assert reconciliation.status is TotalReturnReconciliationStatus.MATERIAL_CONFLICT
    assert reconciliation.blockers == ("TOTAL_RETURN_MATERIAL_PROVIDER_CONFLICT",)
    audit = audit_benchmark_alignment(
        strategy_semantics=ReturnSemantics.POINT_IN_TIME_TOTAL_RETURN,
        strategy_sessions=(date(2024, 2, 1), date(2024, 2, 2)),
        strategy_cutoff=NOW,
        benchmark=BenchmarkEvidence(
            "SPY",
            (date(2024, 2, 1),),
            ReturnSemantics.RAW_PRICE,
            NOW,
            "stooq",
            "America/New_York",
            NOW,
        ),
    )
    assert audit.status is DataQualityStatus.BLOCKED_WITH_EVIDENCE
    assert "BENCHMARK_RETURN_SEMANTICS_MISMATCH" in audit.blockers
    assert "BENCHMARK_SESSION_ALIGNMENT_INCOMPLETE" in audit.blockers


def test_next_session_open_rejects_impossible_same_session_execution() -> None:
    status, blockers = audit_executable_next_session_open(
        ExecutableNextSessionOpen(
            "SEC-A", NOW - timedelta(minutes=1), NOW, "America/New_York", date(2024, 2, 2),
            "NEXT_SESSION_OPEN", NOW, 100.0, 1000, "yahoo_finance", "daily-bar", "raw", NOW,
            False, True, True,
        ),
        expected_next_session_date=date(2024, 2, 5),
    )
    assert status.value == "BLOCKED"
    assert "NEXT_LEGAL_SESSION_MISMATCH" in blockers
    assert "SAME_SESSION_OR_PRE_DECISION_OPEN" in blockers


def test_authority_ledgers_are_append_only_and_conflicts_remain_explicit(
    session_factory: sessionmaker[Session],
) -> None:
    snapshot = create_dataset_snapshot(
        created_at=NOW,
        data_cutoff=NOW - timedelta(minutes=1),
        provider_versions={"sec_edgar": "2024-02"},
        raw_hashes={"sec": "a" * 64},
        normalized_dataset_hashes={"fundamentals": "b" * 64},
        security_master_hash="c" * 64,
        corporate_action_hash="d" * 64,
        benchmark_hash="e" * 64,
        fundamental_hash="f" * 64,
        universe_hash="0" * 64,
        schema_version="round80-v1",
        normalization_version="round80-normalization-v1",
        git_sha="f87c9b550e9ff6bd8955f7b049552c27ec57066c",
    )
    raw = ImmutableRawFetchEvidence(
        "fetch-1", "sec_edgar", DataDomain.FILINGS, "submissions", {"cik": 1},
        NOW - timedelta(seconds=1), NOW, "1" * 64, "sec-v1", "normal-v1", NOW,
        snapshot.snapshot_id,
    )
    conflict = ProviderValueConflict(
        DataDomain.TOTAL_RETURN, "SEC-A", NOW, "internal", "yahoo", 101.0, 104.0, 5.0,
        ProviderConflictResolution.UNRESOLVED_CONFLICT, None, "cross-source material mismatch",
        DataQualityStatus.BLOCKED_WITH_EVIDENCE,
    )
    with session_factory() as session:
        repository = AuthorityEvidenceRepository(session)
        assert repository.persist_raw_fetch(raw).fetch_id == "fetch-1"
        assert repository.persist_raw_fetch(raw).fetch_id == "fetch-1"
        assert repository.persist_dataset_snapshot(snapshot).manifest_hash == snapshot.manifest_hash
        assert (
            repository.persist_provider_conflict(conflict).quality_status
            == "BLOCKED_WITH_EVIDENCE"
        )
        session.commit()


def test_provider_adapter_is_not_promoted_without_certified_pit_audit() -> None:
    provider = default_provider_registry().adapter_for("yahoo_finance").metadata
    universe = build_pit_investable_universe(
        (_candidate("SEC-A", membership=False),), decision_timestamp=NOW,
        minimum_price=5.0, minimum_average_dollar_volume=10_000_000.0, minimum_history_sessions=252,
    )
    from personal_alpha_terminal.data.authority import DomainDataQualityAudit

    audit = DomainDataQualityAudit(
        DataDomain.MARKET_PRICES, None, None, 1, 1, 0.0, 0.0, 0.0,
        DataQualityStatus.PARTIAL, universe.quality_status, DataQualityStatus.PARTIAL,
        None, ("yahoo_finance",),
    )
    gate = evaluate_production_authority_gate(provider=provider, audit=audit)
    assert gate.promotion_allowed is False
    assert "PROVIDER_NOT_PIT_CAPABLE" in gate.blockers


def test_declared_provider_health_never_mistakes_metadata_for_live_availability() -> None:
    health = {
        item.provider_id: item
        for item in declared_provider_health(default_provider_registry().metadata())
    }
    assert health["yahoo_finance"].status.value == "DEGRADED"
    assert health["sec_edgar"].status.value == "AUTH_REQUIRED"
