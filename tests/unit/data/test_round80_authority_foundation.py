"""ROUND80 authority, PIT, SEC, and durable-identity regression coverage."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.data.authority import (
    AuthorityEvidenceRepository,
    DataDomain,
    DataProvenance,
    IdentityResolutionStatus,
    LifecycleEventType,
    PITQuery,
    PITSecurityMaster,
    SecCompanyFact,
    SecEdgarAuthorityAdapter,
    SecurityIdentityVintage,
    SecurityLifecycleEvent,
    default_authority_policy,
    default_provider_registry,
    facts_known_at_or_before,
    latest_facts_known_at_or_before,
    normalize_company_facts,
    parse_sec_former_names,
    parse_sec_submissions,
)


def _time(day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2024, 2, day, hour, minute, tzinfo=UTC)


def _march_time(day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2024, 3, day, hour, minute, tzinfo=UTC)


def _submissions() -> dict[str, object]:
    return {
        "name": "Example Issuer Inc.",
        "filings": {
            "recent": {
                "accessionNumber": ["0000000001-24-000001", "0000000001-24-000002"],
                "form": ["10-Q", "10-Q/A"],
                "filingDate": ["2024-02-02", "2024-03-05"],
                "reportDate": ["2023-12-31", "2023-12-31"],
                "primaryDocument": ["original.htm", "amendment.htm"],
                "acceptanceDateTime": ["2024-02-02T21:30:00Z", "2024-03-05T14:30:00Z"],
            }
        },
    }


def _company_facts() -> dict[str, object]:
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "accn": "0000000001-24-000001",
                                "form": "10-Q",
                                "filed": "2024-02-02",
                                "start": "2023-10-01",
                                "end": "2023-12-31",
                                "val": 100,
                                "fy": 2024,
                                "fp": "Q1",
                            },
                            {
                                "accn": "0000000001-24-000002",
                                "form": "10-Q/A",
                                "filed": "2024-03-05",
                                "start": "2023-10-01",
                                "end": "2023-12-31",
                                "val": 120,
                                "fy": 2024,
                                "fp": "Q1",
                            },
                        ]
                    }
                }
            }
        }
    }


def _normalized_facts() -> tuple[object, tuple[SecCompanyFact, ...]]:
    filings = parse_sec_submissions(_submissions(), cik=1, fetched_at=_march_time(10))
    result = normalize_company_facts(
        _company_facts(),
        cik=1,
        filing_availability=filings,
        fetched_at=_march_time(10),
    )
    assert result.is_complete
    return filings, result.facts


def test_default_authority_registry_does_not_mislabel_operational_prices_as_pit() -> None:
    registry = default_provider_registry()
    policies = {item.domain: item for item in default_authority_policy()}
    price = registry.resolve(policies[DataDomain.MARKET_PRICES])
    actions = registry.resolve(policies[DataDomain.CORPORATE_ACTIONS])
    assert {item.provider_id for item in price.providers} == {"stooq", "yahoo_finance"}
    assert price.status.value == "PARTIAL"
    assert price.warnings == ("MARKET_PRICES:OPERATIONAL_SOURCE_NOT_CERTIFIED_PIT",)
    assert actions.status.value == "BLOCKED_WITH_EVIDENCE"
    assert any("NO_ENABLED_PIT_CAPABLE_PROVIDER" in item for item in actions.blockers)


def test_provenance_keeps_event_time_distinct_from_known_at() -> None:
    provenance = DataProvenance(
        provider_id="sec_edgar",
        source="sec_edgar_companyfacts",
        source_identifier="0000000001-24-000001",
        content_hash="a" * 64,
        vintage="0000000001-24-000001",
        revision_identity="original",
        adjustment_semantics="not_applicable_xbrl_fact",
        observed_at=_time(2, 21, 30),
        available_at=_time(2, 21, 30),
        ingested_at=_time(10),
        fetched_at=_time(10),
        published_at=_time(2, 21, 30),
    )
    assert provenance.known_at == _time(2, 21, 30)


def test_sec_fact_before_after_decision_and_restatement_are_pit_safe() -> None:
    _filings, facts = _normalized_facts()
    before_original = facts_known_at_or_before(facts, _time(2, 21, 29))
    after_original = latest_facts_known_at_or_before(facts, _time(2, 21, 30))
    before_restatement = latest_facts_known_at_or_before(facts, _march_time(5, 14, 29))
    after_restatement = latest_facts_known_at_or_before(facts, _march_time(5, 14, 30))
    assert before_original == ()
    assert len(after_original) == 1 and after_original[0].value == Decimal("100")
    assert len(before_restatement) == 1 and before_restatement[0].value == Decimal("100")
    assert len(after_restatement) == 1 and after_restatement[0].value == Decimal("120")


def test_company_facts_missing_submission_acceptance_stays_blocked() -> None:
    filings = parse_sec_submissions(_submissions(), cik=1, fetched_at=_march_time(10))[:1]
    result = normalize_company_facts(
        _company_facts(),
        cik=1,
        filing_availability=filings,
        fetched_at=_march_time(10),
    )
    assert result.is_complete is False
    assert result.missing_acceptance_accessions == ("0000000001-24-000002",)


def test_sec_former_name_metadata_is_not_backdated_as_pit_evidence() -> None:
    payload = _submissions() | {
        "formerNames": [{"name": "Example Legacy Inc.", "from": "2020-01-01", "to": "2021-03-01"}]
    }
    events = parse_sec_former_names(
        payload,
        cik=1,
        security_id="SEC-EXAMPLE",
        source_known_at=_march_time(10),
        fetched_at=_march_time(11),
    )
    assert len(events) == 1
    assert events[0].effective_date == date(2021, 3, 1)
    assert events[0].known_at == _march_time(10)


def test_sec_adapter_honors_query_cutoff_and_never_returns_future_filing() -> None:
    class Client:
        def fetch_json(self, url: str) -> dict[str, object]:
            return _submissions() if "submissions" in url else _company_facts()

    adapter = SecEdgarAuthorityAdapter(Client(), enabled=True)
    filing_query = PITQuery(
        decision_timestamp=_march_time(1),
        domain=DataDomain.FILINGS,
        permanent_security_id="1",
    )
    fundamentals_query = PITQuery(
        decision_timestamp=_march_time(1),
        domain=DataDomain.FUNDAMENTALS,
        permanent_security_id="1",
    )
    filings = adapter.fetch_raw(filing_query)
    facts = adapter.fetch_raw(fundamentals_query)
    assert [item.provenance.source_identifier for item in filings] == ["0000000001-24-000001"]
    assert [item.provenance.source_identifier for item in facts] == ["0000000001-24-000001"]


def test_pit_identity_handles_rename_reuse_and_multiple_share_classes() -> None:
    base = _time(1)
    master = PITSecurityMaster(
        (
            SecurityIdentityVintage(
                issuer_id="ISSUER-A",
                security_id="SEC-A",
                cik=1,
                ticker="OLD",
                company_name="Example A",
                exchange="NASDAQ",
                security_type="COMMON",
                valid_from=date(2024, 1, 1),
                valid_to=date(2024, 2, 14),
                known_at=base,
                source="sec_edgar",
                source_timestamp=base,
                ingested_at=base + timedelta(days=1),
                confidence=1.0,
            ),
            SecurityIdentityVintage(
                issuer_id="ISSUER-A",
                security_id="SEC-A",
                cik=1,
                ticker="NEW",
                company_name="Example A Renamed",
                exchange="NASDAQ",
                security_type="COMMON",
                valid_from=date(2024, 2, 15),
                known_at=_time(15),
                source="official_exchange",
                source_timestamp=_time(15),
                ingested_at=_time(16),
                confidence=1.0,
            ),
            SecurityIdentityVintage(
                issuer_id="ISSUER-B",
                security_id="SEC-B",
                cik=2,
                ticker="OLD",
                company_name="Unrelated Reuse",
                exchange="NASDAQ",
                security_type="COMMON",
                valid_from=date(2024, 3, 1),
                known_at=_time(3),
                source="official_exchange",
                source_timestamp=_time(3),
                ingested_at=_time(4),
                confidence=1.0,
            ),
            SecurityIdentityVintage(
                issuer_id="ISSUER-C",
                security_id="SEC-C-A",
                cik=3,
                ticker="CLSA",
                company_name="Class A",
                exchange="NYSE",
                security_type="COMMON",
                valid_from=date(2024, 1, 1),
                known_at=base,
                source="sec_edgar",
                source_timestamp=base,
                ingested_at=_time(2),
                confidence=1.0,
            ),
            SecurityIdentityVintage(
                issuer_id="ISSUER-C",
                security_id="SEC-C-B",
                cik=3,
                ticker="CLSB",
                company_name="Class B",
                exchange="NYSE",
                security_type="COMMON",
                valid_from=date(2024, 1, 1),
                known_at=base,
                source="sec_edgar",
                source_timestamp=base,
                ingested_at=_time(2),
                confidence=1.0,
            ),
        )
    )
    old = master.resolve_ticker(ticker="OLD", exchange="NASDAQ", as_of=_time(10))
    renamed = master.resolve_ticker(ticker="NEW", exchange="NASDAQ", as_of=_time(16))
    reused = master.resolve_ticker(
        ticker="OLD", exchange="NASDAQ", as_of=datetime(2024, 3, 5, tzinfo=UTC)
    )
    assert old.status is IdentityResolutionStatus.RESOLVED and old.security is not None
    assert old.security.security_id == "SEC-A"
    assert renamed.security is not None and renamed.security.security_id == "SEC-A"
    assert reused.security is not None and reused.security.security_id == "SEC-B"
    assert master.resolve_cik(cik=3, as_of=_time(10)).status is IdentityResolutionStatus.AMBIGUOUS


def test_lifecycle_events_require_known_at_and_preserve_ticker_change() -> None:
    event = SecurityLifecycleEvent(
        security_id="SEC-A",
        event_type=LifecycleEventType.TICKER_CHANGE,
        effective_date=date(2024, 2, 15),
        known_at=_time(15),
        source="official_exchange",
        source_record_id="notice-1",
        fetched_at=_time(16),
        confidence=0.95,
        event_id="lifecycle-1",
        old_ticker="OLD",
        new_ticker="NEW",
        announcement_timestamp=_time(14),
    )
    assert event.new_ticker == "NEW"
    with pytest.raises(ValueError, match="ticker change"):
        SecurityLifecycleEvent(
            security_id="SEC-A",
            event_type=LifecycleEventType.TICKER_CHANGE,
            effective_date=date(2024, 2, 15),
            known_at=_time(15),
            source="official_exchange",
            source_record_id="notice-2",
            fetched_at=_time(16),
            confidence=0.95,
            event_id="lifecycle-2",
        )


def test_sec_evidence_persistence_is_append_only_and_pit_query_is_safe(
    session_factory: sessionmaker[Session],
) -> None:
    filings, facts = _normalized_facts()
    assert isinstance(filings, tuple)
    with session_factory() as session:
        repository = AuthorityEvidenceRepository(session)
        for fact in facts:
            filing = next(
                item for item in filings if item.accession_number == fact.accession_number
            )
            repository.persist_sec_company_fact(fact, filing=filing)
        session.commit()
        before = repository.sec_facts_as_of(
            cik=1, decision_timestamp=_march_time(5, 14, 29)
        )
        after = repository.sec_facts_as_of(cik=1, decision_timestamp=_march_time(5, 14, 30))
        assert [item.value for item in before] == [Decimal("100")]
        assert [item.value for item in after] == [Decimal("120")]
        duplicate = repository.persist_sec_company_fact(facts[0], filing=filings[0])
        assert duplicate.revision_identity == facts[0].revision_identity
