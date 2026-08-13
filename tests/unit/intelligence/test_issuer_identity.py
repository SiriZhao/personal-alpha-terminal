"""Canonical CIK/issuer security identity resolver and filing evidence tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from personal_alpha_terminal.intelligence.issuer_identity import (
    IssuerIdentityResolver,
    SecurityMappingStatus,
    extract_issuer_identity_candidates,
    import_issuer_security_mappings,
    remap_landing_zone,
)
from personal_alpha_terminal.intelligence.round13_contracts import (
    AcceptedSecEvent,
    build_shadow_features,
)
from personal_alpha_terminal.intelligence.schemas import RawInformation
from personal_alpha_terminal.intelligence.storage import IntelligenceRepository
from personal_alpha_terminal.models import (
    Base,
    IntelligenceRawInformation,
    IssuerSecurityIdentity,
    SecurityMaster,
)


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield test_session
    test_session.close()


def _security(session: Session, ticker: str = "AAPL") -> SecurityMaster:
    security = SecurityMaster(
        canonical_code=f"US:XNAS:{ticker}",
        symbol=ticker,
        name="Apple Inc." if ticker == "AAPL" else ticker,
        market="US",
        exchange="XNAS",
        asset_type="stock",
        currency="USD",
        timezone="America/New_York",
        source="test",
        provider="test",
        available_time=datetime(2020, 1, 1, tzinfo=UTC),
        ingested_time=datetime(2020, 1, 1, tzinfo=UTC),
    )
    session.add(security)
    session.flush()
    return security


def _identity(
    session: Session,
    *,
    cik: int = 320193,
    stock_id: int | None,
    ticker: str,
    effective_from: date,
    effective_to: date | None = None,
    available_at: datetime,
    evidence_identifier: str = "acc-1",
) -> IssuerSecurityIdentity:
    row = IssuerSecurityIdentity(
        cik=cik,
        issuer_id=str(cik),
        issuer_name="Apple Inc.",
        stock_id=stock_id,
        permanent_security_id=f"US:XNAS:{ticker}" if stock_id is not None else None,
        ticker_as_of=ticker if stock_id is not None else None,
        effective_from=effective_from,
        effective_to=effective_to,
        available_at=available_at,
        mapping_source_type="SEC_FILING_PIT_IDENTITY",
        source="sec-edgar-filing-identity",
        source_version="sec-edgar-filing-identity-v1",
        provider="sec-edgar",
        evidence_identifier=evidence_identifier,
        evidence_hash="e" * 64,
        ingested_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    session.add(row)
    session.flush()
    return row


def _raw(
    *,
    body: str,
    issuer_id: str = "320193",
    available_at: datetime | None = None,
) -> RawInformation:
    observed = available_at or datetime(2025, 1, 3, 21, 30, tzinfo=UTC)
    return RawInformation(
        raw_id=f"sec-320193-{issuer_id}",
        source="sec-edgar",
        source_identifier=f"acc-{issuer_id}",
        title="Apple Inc. 8-K acc",
        body=body,
        issuer_id=issuer_id,
        document_type="8-K",
        published_at=observed,
        observed_at=observed,
        ingested_at=observed,
        data_cutoff=observed,
        accepted_at=observed,
        available_at=observed,
    )


def test_resolve_cik_issuer_and_pit_security(session: Session) -> None:
    security = _security(session)
    _identity(
        session,
        stock_id=security.id,
        ticker="AAPL",
        effective_from=date(2024, 1, 1),
        available_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    resolution = IssuerIdentityResolver(session).resolve(
        320193, datetime(2024, 2, 1, tzinfo=UTC)
    )
    assert resolution.issuer_resolved
    assert resolution.security_status is SecurityMappingStatus.SECURITY_MAPPED
    assert resolution.mapping is not None
    mapping = resolution.mapping.security_mapping()
    assert mapping is not None
    assert mapping.permanent_security_id == "US:XNAS:AAPL"
    assert mapping.ticker_as_of == "AAPL"
    assert mapping.source_version == "sec-edgar-filing-identity-v1"


def test_future_mapping_is_excluded(session: Session) -> None:
    security = _security(session)
    _identity(
        session,
        stock_id=security.id,
        ticker="AAPL",
        effective_from=date(2025, 1, 1),
        available_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    resolution = IssuerIdentityResolver(session).resolve(
        320193, datetime(2024, 12, 31, tzinfo=UTC)
    )
    assert "FUTURE_MAPPING_EXCLUDED" in resolution.blockers
    assert resolution.mapping is None


def test_ticker_rename_uses_pit_interval(session: Session) -> None:
    security = _security(session)
    _identity(
        session,
        stock_id=security.id,
        ticker="OLD",
        effective_from=date(2024, 1, 1),
        effective_to=date(2024, 6, 30),
        available_at=datetime(2024, 1, 1, tzinfo=UTC),
        evidence_identifier="old",
    )
    _identity(
        session,
        stock_id=security.id,
        ticker="NEW",
        effective_from=date(2024, 7, 1),
        available_at=datetime(2024, 7, 1, tzinfo=UTC),
        evidence_identifier="new",
    )
    resolver = IssuerIdentityResolver(session)
    assert resolver.security_mapping_for(320193, datetime(2024, 3, 1, tzinfo=UTC)) is not None
    old = resolver.security_mapping_for(320193, datetime(2024, 3, 1, tzinfo=UTC))
    new = resolver.security_mapping_for(320193, datetime(2024, 8, 1, tzinfo=UTC))
    assert old is not None and old.ticker_as_of == "OLD"
    assert new is not None and new.ticker_as_of == "NEW"


def test_multiple_share_classes_are_ambiguous(session: Session) -> None:
    first = _security(session, "GOOG")
    second = _security(session, "GOOGL")
    _identity(
        session,
        stock_id=first.id,
        ticker="GOOG",
        effective_from=date(2024, 1, 1),
        available_at=datetime(2024, 1, 1, tzinfo=UTC),
        evidence_identifier="goog",
    )
    _identity(
        session,
        stock_id=second.id,
        ticker="GOOGL",
        effective_from=date(2024, 1, 1),
        available_at=datetime(2024, 1, 1, tzinfo=UTC),
        evidence_identifier="googl",
    )
    resolution = IssuerIdentityResolver(session).resolve(
        320193, datetime(2024, 2, 1, tzinfo=UTC)
    )
    assert resolution.security_status is SecurityMappingStatus.SECURITY_MAPPING_AMBIGUOUS
    assert resolution.mapping is None


def test_delisted_security_is_blocked(session: Session) -> None:
    security = _security(session)
    security.delist_date = date(2024, 12, 31)
    session.flush()
    _identity(
        session,
        stock_id=security.id,
        ticker="AAPL",
        effective_from=date(2024, 1, 1),
        available_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    resolution = IssuerIdentityResolver(session).resolve(
        320193, datetime(2025, 6, 1, tzinfo=UTC)
    )
    assert resolution.security_status is SecurityMappingStatus.DELISTED_SECURITY
    assert resolution.mapping is None


def test_mapping_unavailable_when_no_identity_row(session: Session) -> None:
    resolution = IssuerIdentityResolver(session).resolve(
        320193, datetime(2024, 2, 1, tzinfo=UTC)
    )
    assert not resolution.issuer_resolved
    assert resolution.mapping is None


def test_filing_identity_extractor_reads_xbrl_and_form4() -> None:
    xbrl = _raw(
        body=(
            "<html><ix:nonNumeric name=\"dei:EntityRegistrantName\">Apple Inc.</ix:nonNumeric>"
            "<ix:nonNumeric name=\"dei:TradingSymbol\">AAPL</ix:nonNumeric></html>"
        )
    )
    form4 = _raw(
        body="Issuer Name and Ticker or Trading Symbol Apple Inc. [ AAPL ]",
        issuer_id="320193",
    )
    candidates = extract_issuer_identity_candidates((xbrl, form4))
    assert len(candidates) == 2
    assert {item.ticker_as_of for item in candidates} == {"AAPL"}
    assert all(item.issuer_name == "Apple Inc." for item in candidates)


def test_import_and_remap_landing_zone(session: Session, tmp_path: Path) -> None:
    security = _security(session)
    raw = _raw(body="Issuer Name and Ticker or Trading Symbol Apple Inc. [ AAPL ]")
    root = tmp_path / "landing" / "acq"
    root.mkdir(parents=True)
    (root / "documents.jsonl").write_text(raw.model_dump_json() + "\n", encoding="utf-8")
    candidates = extract_issuer_identity_candidates((raw,))
    assert import_issuer_security_mappings(session, candidates) == 1
    resolver = IssuerIdentityResolver(session)
    assert remap_landing_zone(tmp_path, resolver) == 1
    remapped = RawInformation.model_validate_json(
        (root / "documents.jsonl").read_text(encoding="utf-8").strip()
    )
    assert remapped.permanent_security_id == security.canonical_code
    assert remapped.ticker_as_of == "AAPL"
    assert remapped.security_mapping_status == "SECURITY_MAPPED"


def test_raw_upsert_persists_unmapped_then_maps(session: Session) -> None:
    raw = _raw(body="Apple Inc. raw body")
    repository = IntelligenceRepository(session)
    repository.upsert_raw(raw)
    session.flush()
    stored = session.scalar(
        select(IntelligenceRawInformation).where(
            IntelligenceRawInformation.raw_id == raw.raw_id
        )
    )
    assert stored is not None
    assert stored.permanent_security_id is None
    assert stored.issuer_id == "320193"
    mapped = raw.model_copy(
        update={
            "permanent_security_id": "US:XNAS:AAPL",
            "ticker_as_of": "AAPL",
            "security_mapping_status": "SECURITY_MAPPED",
            "security_mapping_source": "sec-edgar-filing-identity-v1:acc",
            "security_mapping_source_version": "sec-edgar-filing-identity-v1",
        }
    )
    repository.upsert_raw(mapped)
    session.flush()
    stored = session.scalar(
        select(IntelligenceRawInformation).where(
            IntelligenceRawInformation.raw_id == raw.raw_id
        )
    )
    assert stored is not None
    assert stored.permanent_security_id == "US:XNAS:AAPL"
    assert stored.security_mapping_status == "SECURITY_MAPPED"


def test_shadow_features_skip_unmapped_issuer_events() -> None:
    event = AcceptedSecEvent(
        event_id="a" * 64,
        raw_id="r" * 64,
        issuer_id="320193",
        ticker_asof=None,
        claimed_ticker_asof="AAPL",
        security_mapping_status="BLOCKED_SECURITY_MAPPING",
        event_type="EARNINGS",
        direction="POSITIVE",
        magnitude=1.0,
        materiality="HIGH",
        novelty="NEW",
        horizon="MEDIUM",
        extraction_confidence=0.95,
        source_section="Item 2.02",
        source_span="Revenue increased.",
        summary="Issuer-level evidence-backed event.",
        evidence_hash="e" * 64,
        event_timestamp=datetime(2025, 1, 3, tzinfo=UTC),
        available_at=datetime(2025, 1, 3, tzinfo=UTC),
        model_provider="deepseek",
        model_name="deepseek-v4-flash",
        response_hash="f" * 64,
        prompt_version="sec-pit-event-extraction-v1",
    )
    features = build_shadow_features((event,), as_of=datetime(2025, 1, 4, tzinfo=UTC))
    assert features == ()
