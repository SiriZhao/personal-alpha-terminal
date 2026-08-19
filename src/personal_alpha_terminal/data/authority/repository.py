"""Persistence adapter for imported authoritative lifecycle and SEC evidence.

All writes are append-only at the source/revision identity level. This module
does not fetch a provider and is never called by terminal fast-start.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.data.authority.identity import SecurityLifecycleEvent
from personal_alpha_terminal.data.authority.sec_edgar import (
    SecCompanyFact,
    SecFilingAvailability,
)
from personal_alpha_terminal.models import (
    SecCompanyFactEvidence,
    SecFilingEvidence,
)
from personal_alpha_terminal.models import (
    SecurityLifecycleEvent as SecurityLifecycleEventRecord,
)


class ImmutableEvidenceConflict(ValueError):
    """Raised when a source identity is reused with different immutable content."""


class AuthorityEvidenceRepository:
    """Persist and query immutable source-native evidence behind PIT cutoffs."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def persist_lifecycle_event(
        self,
        event: SecurityLifecycleEvent,
        *,
        stock_id: int | None = None,
        issuer_id: str | None = None,
        content_hash: str,
    ) -> SecurityLifecycleEventRecord:
        if not content_hash.strip():
            raise ValueError("lifecycle content_hash is required")
        existing = self.session.scalar(
            select(SecurityLifecycleEventRecord).where(
                SecurityLifecycleEventRecord.event_id == event.event_id,
                SecurityLifecycleEventRecord.source == event.source,
                SecurityLifecycleEventRecord.source_record_id == event.source_record_id,
            )
        )
        if existing is not None:
            if existing.content_hash != content_hash:
                raise ImmutableEvidenceConflict("security lifecycle source record content changed")
            return existing
        record = SecurityLifecycleEventRecord(
            event_id=event.event_id,
            stock_id=stock_id,
            issuer_id=issuer_id,
            security_id=event.security_id,
            event_type=event.event_type.value,
            old_ticker=event.old_ticker,
            new_ticker=event.new_ticker,
            old_name=event.old_name,
            new_name=event.new_name,
            effective_date=event.effective_date,
            announcement_timestamp=event.announcement_timestamp,
            known_at=event.known_at,
            fetched_at=event.fetched_at,
            exchange=event.exchange,
            reason=event.reason,
            predecessor_security_id=event.predecessor_security_id,
            successor_security_id=event.successor_security_id,
            source=event.source,
            source_record_id=event.source_record_id,
            content_hash=content_hash,
            confidence=Decimal(str(event.confidence)),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def persist_sec_filing(self, filing: SecFilingAvailability) -> SecFilingEvidence:
        existing = self.session.scalar(
            select(SecFilingEvidence).where(
                SecFilingEvidence.cik == filing.cik,
                SecFilingEvidence.accession_number == filing.accession_number,
            )
        )
        content_hash = _filing_hash(filing)
        revision_identity = f"SEC-FILING:{filing.cik}:{filing.accession_number}"
        if existing is not None:
            if (
                existing.content_hash != content_hash
                or existing.revision_identity != revision_identity
            ):
                raise ImmutableEvidenceConflict("SEC filing accession content changed")
            return existing
        record = SecFilingEvidence(
            cik=filing.cik,
            issuer_id=f"SEC-CIK-{filing.cik:010d}",
            issuer_name=filing.issuer_name,
            accession_number=filing.accession_number,
            form=filing.form,
            filing_date=filing.filing_date,
            report_period_end=filing.report_period_end,
            acceptance_datetime=filing.acceptance_datetime,
            known_at=filing.known_at,
            fetched_at=filing.fetched_at,
            primary_document=filing.primary_document,
            source="sec_edgar",
            source_url=(
                "https://data.sec.gov/submissions/CIK" f"{filing.cik:010d}.json"
            ),
            content_hash=content_hash,
            revision_identity=revision_identity,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def persist_sec_company_fact(
        self,
        fact: SecCompanyFact,
        *,
        filing: SecFilingAvailability,
        stock_id: int | None = None,
    ) -> SecCompanyFactEvidence:
        if fact.cik != filing.cik or fact.accession_number != filing.accession_number:
            raise ValueError("SEC Company Fact must reference its matching filing accession")
        if fact.acceptance_datetime != filing.acceptance_datetime:
            raise ValueError("SEC Company Fact acceptance must match its filing")
        filing_record = self.persist_sec_filing(filing)
        existing = self.session.scalar(
            select(SecCompanyFactEvidence).where(
                SecCompanyFactEvidence.revision_identity == fact.revision_identity
            )
        )
        if existing is not None:
            if existing.content_hash != fact.content_hash:
                raise ImmutableEvidenceConflict("SEC Company Fact revision content changed")
            return existing
        record = SecCompanyFactEvidence(
            filing_id=filing_record.id,
            stock_id=stock_id,
            issuer_id=fact.issuer_id,
            cik=fact.cik,
            taxonomy=fact.taxonomy,
            concept=fact.concept,
            value=fact.value,
            unit=fact.unit,
            period_start=fact.period_start,
            period_end=fact.period_end,
            fiscal_year=fact.fiscal_year,
            fiscal_period=fact.fiscal_period,
            form=fact.form,
            filing_date=fact.filing_date,
            acceptance_datetime=fact.acceptance_datetime,
            accession_number=fact.accession_number,
            source=fact.source,
            known_at=fact.known_at,
            fetched_at=fact.fetched_at,
            revision_identity=fact.revision_identity,
            content_hash=fact.content_hash,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def sec_facts_as_of(
        self,
        *,
        cik: int,
        decision_timestamp: datetime,
    ) -> tuple[SecCompanyFactEvidence, ...]:
        """Latest public SEC fact per exact period, with no future restatement."""

        if cik <= 0:
            raise ValueError("CIK must be positive")
        if decision_timestamp.tzinfo is None or decision_timestamp.utcoffset() is None:
            raise ValueError("decision_timestamp must be timezone-aware")
        records = tuple(
            self.session.scalars(
                select(SecCompanyFactEvidence)
                .where(
                    SecCompanyFactEvidence.cik == cik,
                    SecCompanyFactEvidence.known_at <= decision_timestamp,
                )
                .order_by(
                    SecCompanyFactEvidence.known_at,
                    SecCompanyFactEvidence.revision_identity,
                )
            )
        )
        selected: dict[tuple[str, str, object, object, str], SecCompanyFactEvidence] = {}
        for record in records:
            key = (
                record.taxonomy,
                record.concept,
                record.period_start,
                record.period_end,
                record.unit,
            )
            current = selected.get(key)
            if current is None or (record.known_at, record.revision_identity) > (
                current.known_at,
                current.revision_identity,
            ):
                selected[key] = record
        return tuple(sorted(selected.values(), key=lambda item: item.revision_identity))


def _filing_hash(filing: SecFilingAvailability) -> str:
    document = {
        "cik": filing.cik,
        "issuer_name": filing.issuer_name,
        "accession_number": filing.accession_number,
        "form": filing.form,
        "filing_date": filing.filing_date.isoformat(),
        "report_period_end": (
            filing.report_period_end.isoformat() if filing.report_period_end is not None else None
        ),
        "acceptance_datetime": filing.acceptance_datetime.isoformat(),
        "primary_document": filing.primary_document,
    }
    return sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
