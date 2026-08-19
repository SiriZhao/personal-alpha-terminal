"""SEC EDGAR filings and Company Facts normalized with acceptance-time PIT gates.

This module makes no request on import.  Filing date and local fetch time are
never substituted for SEC acceptance time when determining ``known_at``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Protocol, cast

from personal_alpha_terminal.data.authority.contracts import (
    AuthorityTier,
    CanonicalObservation,
    DataDomain,
    DataProvenance,
    PITQuery,
    ProviderMetadata,
    ProviderRole,
    RawObservation,
)
from personal_alpha_terminal.data.authority.identity import (
    LifecycleEventType,
    SecurityLifecycleEvent,
)

SEC_EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_EDGAR_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_EDGAR_PROVIDER_ID = "sec_edgar"


class SecEdgarClientPort(Protocol):
    def fetch_json(self, url: str) -> dict[str, Any]: ...


def _aware_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return _aware_utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")), name)


@dataclass(frozen=True, slots=True)
class SecFilingAvailability:
    cik: int
    issuer_name: str
    accession_number: str
    form: str
    filing_date: date
    acceptance_datetime: datetime
    fetched_at: datetime
    report_period_end: date | None = None
    primary_document: str | None = None

    def __post_init__(self) -> None:
        if self.cik <= 0 or not all(
            value.strip() for value in (self.issuer_name, self.accession_number, self.form)
        ):
            raise ValueError("SEC filing identity is incomplete")
        acceptance = _aware_utc(self.acceptance_datetime, "acceptance_datetime")
        fetched = _aware_utc(self.fetched_at, "fetched_at")
        if acceptance > fetched:
            raise ValueError("acceptance_datetime cannot be after fetched_at")
        object.__setattr__(self, "acceptance_datetime", acceptance)
        object.__setattr__(self, "fetched_at", fetched)

    @property
    def known_at(self) -> datetime:
        return self.acceptance_datetime


@dataclass(frozen=True, slots=True)
class SecCompanyFact:
    issuer_id: str
    cik: int
    taxonomy: str
    concept: str
    value: Decimal
    unit: str
    period_end: date
    form: str
    filing_date: date
    acceptance_datetime: datetime
    accession_number: str
    source: str
    known_at: datetime
    fetched_at: datetime
    revision_identity: str
    content_hash: str
    period_start: date | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None

    def __post_init__(self) -> None:
        if self.cik <= 0 or not all(
            value.strip()
            for value in (
                self.issuer_id,
                self.taxonomy,
                self.concept,
                self.unit,
                self.form,
                self.accession_number,
                self.source,
                self.revision_identity,
                self.content_hash,
            )
        ):
            raise ValueError("SEC Company Fact identity is incomplete")
        acceptance = _aware_utc(self.acceptance_datetime, "acceptance_datetime")
        known = _aware_utc(self.known_at, "known_at")
        fetched = _aware_utc(self.fetched_at, "fetched_at")
        if known != acceptance:
            raise ValueError("known_at must equal accession acceptance_datetime")
        if known > fetched:
            raise ValueError("known_at cannot be after fetched_at")
        object.__setattr__(self, "acceptance_datetime", acceptance)
        object.__setattr__(self, "known_at", known)
        object.__setattr__(self, "fetched_at", fetched)

    @property
    def period_key(self) -> tuple[str, int, str, str, date | None, date, str]:
        return (
            self.issuer_id,
            self.cik,
            self.taxonomy,
            self.concept,
            self.period_start,
            self.period_end,
            self.unit,
        )


@dataclass(frozen=True, slots=True)
class CompanyFactsNormalizationResult:
    facts: tuple[SecCompanyFact, ...]
    missing_acceptance_accessions: tuple[str, ...]
    rejected_rows: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        return not self.missing_acceptance_accessions and not self.rejected_rows


def parse_sec_submissions(
    payload: Mapping[str, object], *, cik: int, fetched_at: datetime
) -> tuple[SecFilingAvailability, ...]:
    """Parse submissions rows with their exact SEC acceptance datetimes."""

    if cik <= 0:
        raise ValueError("CIK must be positive")
    fetched = _aware_utc(fetched_at, "fetched_at")
    issuer_name = _required_text(payload, "name")
    filings = payload.get("filings")
    if not isinstance(filings, Mapping):
        raise ValueError("SEC submissions missing filings")
    records: list[SecFilingAvailability] = []
    for row in _submission_rows(filings.get("recent")):
        report_raw = row.get("reportDate")
        records.append(
            SecFilingAvailability(
                cik=cik,
                issuer_name=issuer_name,
                accession_number=_required_text(row, "accessionNumber"),
                form=_required_text(row, "form"),
                filing_date=date.fromisoformat(_required_text(row, "filingDate")),
                acceptance_datetime=_time(row.get("acceptanceDateTime"), "acceptanceDateTime"),
                fetched_at=fetched,
                report_period_end=date.fromisoformat(str(report_raw)) if report_raw else None,
                primary_document=_optional_text(row.get("primaryDocument")),
            )
        )
    return tuple(sorted(records, key=lambda item: (item.known_at, item.accession_number)))


def parse_sec_former_names(
    payload: Mapping[str, object],
    *,
    cik: int,
    security_id: str,
    source_known_at: datetime,
    fetched_at: datetime,
) -> tuple[SecurityLifecycleEvent, ...]:
    """Normalize SEC ``formerNames`` metadata without backdating its availability.

    SEC submissions can disclose historical former-name intervals, but the
    response itself is a current snapshot.  The caller must supply when that
    snapshot was actually available; using an old effective date as ``known_at``
    would leak current SEC metadata into prior decisions.
    """

    if cik <= 0 or not security_id.strip():
        raise ValueError("CIK and security_id are required")
    known = _aware_utc(source_known_at, "source_known_at")
    fetched = _aware_utc(fetched_at, "fetched_at")
    if known > fetched:
        raise ValueError("source_known_at cannot be after fetched_at")
    issuer_name = _required_text(payload, "name")
    rows = payload.get("formerNames", [])
    if rows is None:
        return ()
    if not isinstance(rows, list):
        raise ValueError("SEC formerNames must be a list when supplied")
    events: list[SecurityLifecycleEvent] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError("SEC formerNames row must be an object")
        former_name = _required_text(row, "name")
        effective = date.fromisoformat(_required_text(row, "to"))
        start = _optional_date(row.get("from"))
        source_record_id = (
            f"CIK{cik:010d}:former-name:{index}:{former_name}:{effective.isoformat()}"
        )
        events.append(
            SecurityLifecycleEvent(
                security_id=security_id,
                event_type=LifecycleEventType.NAME_CHANGE,
                effective_date=effective,
                known_at=known,
                source="sec_edgar_submissions",
                source_record_id=source_record_id,
                fetched_at=fetched,
                confidence=0.75,
                event_id="SEC-NAME-" + sha256(source_record_id.encode("utf-8")).hexdigest()[:24],
                old_name=former_name,
                new_name=issuer_name,
                reason=(
                    "SEC formerNames metadata; point-in-time use begins only at "
                    "source_known_at, not the historical effective date"
                ),
                predecessor_security_id=None,
                successor_security_id=None,
                announcement_timestamp=(
                    datetime.combine(start, time.min, tzinfo=UTC) if start is not None else None
                ),
            )
        )
    return tuple(sorted(events, key=lambda item: (item.effective_date, item.event_id)))


def normalize_company_facts(
    payload: Mapping[str, object],
    *,
    cik: int,
    filing_availability: Sequence[SecFilingAvailability],
    fetched_at: datetime,
) -> CompanyFactsNormalizationResult:
    """Reject Company Facts without a matching accession acceptance timestamp."""

    fetched = _aware_utc(fetched_at, "fetched_at")
    available = {item.accession_number: item for item in filing_availability if item.cik == cik}
    root = payload.get("facts")
    if not isinstance(root, Mapping):
        raise ValueError("SEC Company Facts payload is missing facts")
    facts: list[SecCompanyFact] = []
    missing: set[str] = set()
    rejected: list[str] = []
    for taxonomy, concepts in sorted(root.items(), key=lambda item: str(item[0])):
        if not isinstance(taxonomy, str) or not isinstance(concepts, Mapping):
            rejected.append("INVALID_TAXONOMY_CONTAINER")
            continue
        for concept, description in sorted(concepts.items(), key=lambda item: str(item[0])):
            if not isinstance(concept, str) or not isinstance(description, Mapping):
                rejected.append("INVALID_CONCEPT_CONTAINER")
                continue
            units = description.get("units")
            if not isinstance(units, Mapping):
                rejected.append(f"{taxonomy}:{concept}:MISSING_UNITS")
                continue
            for unit, rows in sorted(units.items(), key=lambda item: str(item[0])):
                if not isinstance(unit, str) or not isinstance(rows, list):
                    rejected.append(f"{taxonomy}:{concept}:INVALID_UNIT_ROWS")
                    continue
                for index, row in enumerate(rows):
                    if not isinstance(row, Mapping):
                        rejected.append(f"{taxonomy}:{concept}:{unit}:{index}:INVALID_ROW")
                        continue
                    try:
                        accession = _required_text(row, "accn")
                        filing = available.get(accession)
                        if filing is None:
                            missing.add(accession)
                            continue
                        form = _required_text(row, "form")
                        filed = date.fromisoformat(_required_text(row, "filed"))
                        if form != filing.form or filed != filing.filing_date:
                            rejected.append(f"{taxonomy}:{concept}:{unit}:{accession}:FILING_MISMATCH")
                            continue
                        period_start = _optional_date(row.get("start"))
                        period_end = date.fromisoformat(_required_text(row, "end"))
                        value = _decimal(row.get("val"))
                    except (TypeError, ValueError) as error:
                        rejected.append(f"{taxonomy}:{concept}:{unit}:{index}:{type(error).__name__}")
                        continue
                    source_row = {
                        "cik": cik,
                        "taxonomy": taxonomy,
                        "concept": concept,
                        "unit": unit,
                        "row": dict(row),
                    }
                    content_hash = _hash(source_row)
                    revision = ":".join(
                        (
                            str(cik),
                            taxonomy,
                            concept,
                            accession,
                            unit,
                            period_start.isoformat() if period_start else "INSTANT",
                            period_end.isoformat(),
                            content_hash,
                        )
                    )
                    facts.append(
                        SecCompanyFact(
                            issuer_id=f"SEC-CIK-{cik:010d}",
                            cik=cik,
                            taxonomy=taxonomy,
                            concept=concept,
                            value=value,
                            unit=unit,
                            period_start=period_start,
                            period_end=period_end,
                            fiscal_year=_optional_int(row.get("fy")),
                            fiscal_period=_optional_text(row.get("fp")),
                            form=form,
                            filing_date=filed,
                            acceptance_datetime=filing.acceptance_datetime,
                            accession_number=accession,
                            source="sec_edgar_companyfacts",
                            known_at=filing.known_at,
                            fetched_at=fetched,
                            revision_identity=revision,
                            content_hash=content_hash,
                        )
                    )
    return CompanyFactsNormalizationResult(
        facts=tuple(
            sorted(
                facts,
                key=lambda item: (
                    item.known_at,
                    item.taxonomy,
                    item.concept,
                    item.revision_identity,
                ),
            )
        ),
        missing_acceptance_accessions=tuple(sorted(missing)),
        rejected_rows=tuple(sorted(set(rejected))),
    )


def facts_known_at_or_before(
    facts: Sequence[SecCompanyFact], decision_timestamp: datetime
) -> tuple[SecCompanyFact, ...]:
    cutoff = _aware_utc(decision_timestamp, "decision_timestamp")
    return tuple(
        sorted(
            (item for item in facts if item.known_at <= cutoff),
            key=lambda item: item.revision_identity,
        )
    )


def latest_facts_known_at_or_before(
    facts: Sequence[SecCompanyFact], decision_timestamp: datetime
) -> tuple[SecCompanyFact, ...]:
    """Newest allowed restatement per period, only after it actually became public."""

    selected: dict[tuple[str, int, str, str, date | None, date, str], SecCompanyFact] = {}
    for fact in facts_known_at_or_before(facts, decision_timestamp):
        current = selected.get(fact.period_key)
        if current is None or (fact.known_at, fact.revision_identity) > (
            current.known_at,
            current.revision_identity,
        ):
            selected[fact.period_key] = fact
    return tuple(sorted(selected.values(), key=lambda item: item.period_key))


def company_fact_to_canonical_observation(
    fact: SecCompanyFact,
    *,
    permanent_security_id: str | None = None,
    symbol_at_time: str | None = None,
) -> CanonicalObservation:
    provenance = DataProvenance(
        provider_id=SEC_EDGAR_PROVIDER_ID,
        source=fact.source,
        source_identifier=fact.accession_number,
        content_hash=fact.content_hash,
        vintage=fact.accession_number,
        revision_identity=fact.revision_identity,
        adjustment_semantics="not_applicable_xbrl_fact",
        observed_at=fact.acceptance_datetime,
        published_at=fact.acceptance_datetime,
        available_at=fact.known_at,
        ingested_at=fact.fetched_at,
        fetched_at=fact.fetched_at,
        source_url=SEC_EDGAR_COMPANY_FACTS_URL.format(cik=fact.cik),
    )
    raw = RawObservation(
        observation_id=f"sec-companyfact:{fact.revision_identity}",
        domain=DataDomain.FUNDAMENTALS,
        effective_at=datetime.combine(fact.period_end, time.min, tzinfo=UTC),
        provenance=provenance,
        payload=cast(Mapping[str, object], asdict(fact)),
        permanent_security_id=permanent_security_id,
        symbol_at_time=symbol_at_time,
    )
    return CanonicalObservation.from_raw(raw, values=cast(Mapping[str, object], asdict(fact)))


@dataclass(frozen=True, slots=True)
class SecEdgarAuthorityAdapter:
    """Explicit remote adapter; it is not registered in normal terminal startup."""

    client: SecEdgarClientPort
    enabled: bool = False

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_id=SEC_EDGAR_PROVIDER_ID,
            data_domains=frozenset({DataDomain.FILINGS, DataDomain.FUNDAMENTALS}),
            authority_tier=AuthorityTier.OFFICIAL,
            pit_capable=True,
            timestamp_semantics="acceptance datetime is known_at; missing acceptance is rejected",
            adjustment_semantics="not applicable to filings and XBRL facts",
            credential_required=True,
            coverage_notes="Requires an explicit compliant SEC client; not a certification bypass.",
            fallback_role=ProviderRole.PRIMARY,
            enabled=self.enabled,
        )

    def fetch_raw(self, query: PITQuery) -> tuple[RawObservation, ...]:
        if query.domain not in {DataDomain.FILINGS, DataDomain.FUNDAMENTALS}:
            raise ValueError(f"SEC EDGAR does not provide {query.domain.value}")
        if not self.enabled:
            raise RuntimeError("SEC EDGAR adapter is disabled; configure it explicitly")
        if query.permanent_security_id is None or not query.permanent_security_id.isdecimal():
            raise ValueError("SEC EDGAR query permanent_security_id must be numeric CIK")
        cik = int(query.permanent_security_id)
        fetched = datetime.now(UTC)
        filings = parse_sec_submissions(
            self.client.fetch_json(SEC_EDGAR_SUBMISSIONS_URL.format(cik=cik)),
            cik=cik,
            fetched_at=fetched,
        )
        if query.domain is DataDomain.FILINGS:
            return tuple(
                _filing_raw(item)
                for item in filings
                if item.known_at <= query.decision_timestamp
            )
        result = normalize_company_facts(
            self.client.fetch_json(SEC_EDGAR_COMPANY_FACTS_URL.format(cik=cik)),
            cik=cik,
            filing_availability=filings,
            fetched_at=fetched,
        )
        if not result.is_complete:
            raise ValueError(
                "SEC Company Facts missing acceptance provenance or valid filing metadata"
            )
        return tuple(
            _canonical_to_raw(
                company_fact_to_canonical_observation(
                    fact,
                    permanent_security_id=str(cik),
                )
            )
            for fact in facts_known_at_or_before(result.facts, query.decision_timestamp)
        )


def _filing_raw(filing: SecFilingAvailability) -> RawObservation:
    provenance = DataProvenance(
        provider_id=SEC_EDGAR_PROVIDER_ID,
        source="sec_edgar_submissions",
        source_identifier=filing.accession_number,
        content_hash=_hash(asdict(filing)),
        vintage=filing.accession_number,
        revision_identity=f"SEC-FILING:{filing.cik}:{filing.accession_number}",
        adjustment_semantics="not_applicable_filing",
        observed_at=filing.acceptance_datetime,
        published_at=filing.acceptance_datetime,
        available_at=filing.known_at,
        ingested_at=filing.fetched_at,
        fetched_at=filing.fetched_at,
        source_url=SEC_EDGAR_SUBMISSIONS_URL.format(cik=filing.cik),
    )
    return RawObservation(
        observation_id=f"sec-filing:{filing.cik}:{filing.accession_number}",
        domain=DataDomain.FILINGS,
        effective_at=filing.acceptance_datetime,
        provenance=provenance,
        payload=cast(Mapping[str, object], asdict(filing)),
        permanent_security_id=str(filing.cik),
    )


def _canonical_to_raw(observation: CanonicalObservation) -> RawObservation:
    return RawObservation(
        observation_id=observation.raw_observation_id,
        domain=observation.domain,
        effective_at=observation.effective_at,
        provenance=observation.provenance,
        payload=observation.values,
        permanent_security_id=observation.permanent_security_id,
        symbol_at_time=observation.symbol_at_time,
    )


def _submission_rows(value: object) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, Mapping))
    if not isinstance(value, Mapping):
        raise ValueError("SEC submissions recent rows are unavailable")
    columns = tuple((key, row) for key, row in value.items() if isinstance(row, list))
    if not columns or len({len(row) for _key, row in columns}) != 1:
        raise ValueError("SEC submissions columns are invalid")
    keys = tuple(key for key, _row in columns)
    return tuple(
        cast(Mapping[str, object], dict(zip(keys, values, strict=True)))
        for values in zip(*(row for _key, row in columns), strict=True)
    )


def _required_text(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_date(value: object) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("fiscal year cannot be boolean")
    return int(value) if isinstance(value, (int, str)) else None


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("Company Fact val must be numeric")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Company Fact val must be decimal") from error
    if not parsed.is_finite():
        raise ValueError("Company Fact val must be finite")
    return parsed


def _hash(value: object) -> str:
    return sha256(
        json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
