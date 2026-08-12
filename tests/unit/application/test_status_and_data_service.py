from datetime import UTC, date, datetime
from pathlib import Path

from personal_alpha_terminal.application.app_service import ApplicationService
from personal_alpha_terminal.application.data_lineage_certification import (
    BarCoverageEvidence,
    CorporateActionCertificate,
    CorporateActionSymbolEvidence,
    EvidenceStatus,
    LineageEvidenceBundle,
    ProviderReconciliationCertificate,
    ReconciliationSymbolEvidence,
)
from personal_alpha_terminal.application.data_service import DataService
from personal_alpha_terminal.application.universe import MINIMUM_US_RESEARCH_UNIVERSE
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.market_data.schemas import (
    DailyUpdateReport,
    InstrumentUpdateResult,
)
from personal_alpha_terminal.models import (
    DataSnapshotManifest,
    ExchangeSession,
    MarketUniverseMember,
    MarketUniverseSnapshot,
)


def _successful_report() -> DailyUpdateReport:
    return DailyUpdateReport(
        started_on=date(2026, 8, 1),
        results=tuple(
            InstrumentUpdateResult(
                symbol=asset.ticker,
                market="US",
                source="yahoo",
                provider="yfinance:download",
                status="success",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 8, 1),
                fetched_count=22,
                valid_count=22,
                inserted_count=22,
            )
            for asset in MINIMUM_US_RESEARCH_UNIVERSE
        ),
        provider_reconciled=True,
        corporate_action_certified=True,
    )


def _fixture_lineage(_session, _settings, start_date, end_date, decision_time):
    action_results = tuple(
        CorporateActionSymbolEvidence(asset.ticker, EvidenceStatus.PASS, 0, ())
        for asset in MINIMUM_US_RESEARCH_UNIVERSE
    )
    reconciliation_results = tuple(
        ReconciliationSymbolEvidence(
            asset.ticker,
            EvidenceStatus.PASS,
            "fixture-secondary",
            22,
            22,
            22,
            1.0,
            0,
            0,
            "fixture paths match",
        )
        for asset in MINIMUM_US_RESEARCH_UNIVERSE
    )
    return LineageEvidenceBundle(
        CorporateActionCertificate(
            EvidenceStatus.PASS,
            "fixture-actions",
            "fixture-only",
            datetime(2026, 1, 9, 22, tzinfo=UTC),
            tuple(asset.ticker for asset in MINIMUM_US_RESEARCH_UNIVERSE),
            0,
            "fixture",
            "fixture",
            (),
            action_results,
            (),
            "a" * 64,
        ),
        ProviderReconciliationCertificate(
            EvidenceStatus.PASS,
            "fixture-primary",
            ("fixture-secondary",),
            1.0,
            0.01,
            0.05,
            reconciliation_results,
            "b" * 64,
        ),
        tuple(
            BarCoverageEvidence(
                asset.ticker, asset.required, 22, 22, 0, 0, 0, 0, 22, end_date
            )
            for asset in MINIMUM_US_RESEARCH_UNIVERSE
        ),
        decision_time,
        end_date,
        "fixture-only",
    )


def test_empty_database_is_not_program_error(session_factory, tmp_path: Path) -> None:
    settings = Settings(database_url="sqlite://")
    service = ApplicationService(session_factory, settings, snapshot_root=tmp_path)

    health = service.get_system_health()

    assert health.program.code == "READY"
    assert health.database.code == "READY"
    assert health.data.code == "EMPTY"
    assert health.model.code == "INSUFFICIENT_DATA"
    assert not hasattr(health, "paper")


def test_real_snapshot_manifest_is_immutable_and_traceable(
    session_factory, tmp_path: Path
) -> None:
    settings = Settings(database_url="sqlite://")
    with session_factory.begin() as session:
        service = DataService(
            session,
            settings,
            snapshot_root=tmp_path,
            sync_runner=lambda _session, _start, _end: _successful_report(),
            lineage_runner=_fixture_lineage,
        )
        outcome = service.sync_market_data(
            start_date=date(2026, 7, 1), end_date=date(2026, 8, 1)
        )
        assert outcome.status == "CERTIFIED"
        manifest = session.query(DataSnapshotManifest).one()
        assert manifest.content_hash
        assert manifest.is_demo is False
        assert manifest.raw_row_count == 22 * len(MINIMUM_US_RESEARCH_UNIVERSE)

    payload = outcome.manifest_path.read_text(encoding="utf-8")
    assert '"certification_result": "CERTIFIED"' in payload
    assert '"provider_name": "yahoo"' in payload


def test_required_provider_failure_blocks_snapshot(session_factory, tmp_path: Path) -> None:
    report = _successful_report()
    first = report.results[0]
    failed = InstrumentUpdateResult(
        symbol=first.symbol,
        market="US",
        source="yahoo",
        provider="yfinance:download",
        status="failed",
        start_date=first.start_date,
        end_date=first.end_date,
        error="network unavailable",
    )
    partial = DailyUpdateReport(report.started_on, (failed, *report.results[1:]))
    with session_factory.begin() as session:
        service = DataService(
            session,
            Settings(database_url="sqlite://"),
            snapshot_root=tmp_path,
            sync_runner=lambda _session, _start, _end: partial,
            lineage_runner=_fixture_lineage,
        )
        outcome = service.sync_market_data(
            start_date=date(2026, 7, 1), end_date=date(2026, 8, 1)
        )
        assert outcome.status == "BLOCKED"
        assert first.symbol in outcome.failed_symbols


def test_status_detail_is_serializable(session_factory, tmp_path: Path) -> None:
    service = ApplicationService(
        session_factory,
        Settings(database_url="sqlite://"),
        snapshot_root=tmp_path,
    )
    status = service.get_data_readiness()
    assert status.updated_at <= datetime.now(UTC)
    assert isinstance(status.code, str)


def test_minimum_universe_uses_machine_segments_not_human_roles(
    session_factory, tmp_path: Path
) -> None:
    with session_factory.begin() as session:
        service = DataService(
            session,
            Settings(database_url="sqlite://"),
            snapshot_root=tmp_path,
            sync_runner=lambda _session, _start, _end: _successful_report(),
            lineage_runner=_fixture_lineage,
        )
        service.initialize_research_database(
            start_date=date(2026, 7, 1), end_date=date(2026, 8, 1)
        )
        members = list(session.query(MarketUniverseMember).all())

    assert {item.segment for item in members} == {"nasdaq", "nyse", "us_etf", "us_index"}
    assert {item.size_bucket for item in members} == {"unknown"}
    assert {item.listing_age_bucket for item in members} == {"unknown"}
    assert all("minimum liquid research universe:" in item.reason for item in members)


def test_sync_repairs_an_existing_empty_current_universe_snapshot(
    session_factory, tmp_path: Path
) -> None:
    with session_factory.begin() as session:
        session.add(
            MarketUniverseSnapshot(
                market="US",
                as_of_date=date(2026, 8, 1),
                source="console_minimum_universe",
                provider="application_config",
                available_time=datetime(2026, 8, 1, tzinfo=UTC),
                ingested_time=datetime(2026, 8, 1, tzinfo=UTC),
            )
        )
        session.flush()
        service = DataService(
            session,
            Settings(database_url="sqlite://"),
            snapshot_root=tmp_path,
            sync_runner=lambda _session, _start, _end: _successful_report(),
            lineage_runner=_fixture_lineage,
        )
        service.sync_market_data(
            start_date=date(2026, 7, 1), end_date=date(2026, 8, 1)
        )
        members = tuple(session.query(MarketUniverseMember).all())

    assert len(members) == len(MINIMUM_US_RESEARCH_UNIVERSE)


def test_sync_populates_certified_exchange_calendar(
    session_factory, tmp_path: Path
) -> None:
    with session_factory.begin() as session:
        service = DataService(
            session,
            Settings(database_url="sqlite://"),
            snapshot_root=tmp_path,
            sync_runner=lambda _session, _start, _end: _successful_report(),
            lineage_runner=_fixture_lineage,
        )
        service.sync_market_data(
            start_date=date(2026, 7, 1),
            end_date=date(2026, 8, 1),
        )
        sessions = tuple(
            session.query(ExchangeSession)
            .filter(ExchangeSession.source == "exchange_calendars")
            .all()
        )
    assert sessions
    assert all(item.is_open for item in sessions)
    assert all(item.open_time is not None for item in sessions)
