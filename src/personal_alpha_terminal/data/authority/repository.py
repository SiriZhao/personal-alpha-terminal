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
from personal_alpha_terminal.data.authority.research_foundation import (
    HistoricalIndexConstituent,
    ImmutableRawFetchEvidence,
    ProviderValueConflict,
    ResearchDatasetSnapshot,
)
from personal_alpha_terminal.data.authority.sec_edgar import (
    SecCompanyFact,
    SecFilingAvailability,
)
from personal_alpha_terminal.models import (
    AuthorityDatasetSnapshotRecord,
    AuthorityProviderConflictRecord,
    AuthorityRawFetchEvidence,
    HistoricalIndexConstituentEvidence,
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

    def persist_raw_fetch(
        self, evidence: ImmutableRawFetchEvidence
    ) -> AuthorityRawFetchEvidence:
        """Persist a content-addressed fetch receipt without overwriting history."""

        existing = self.session.scalar(
            select(AuthorityRawFetchEvidence).where(
                AuthorityRawFetchEvidence.immutable_identity == evidence.immutable_identity
            )
        )
        if existing is not None:
            return existing
        fetch_id_existing = self.session.scalar(
            select(AuthorityRawFetchEvidence).where(
                AuthorityRawFetchEvidence.fetch_id == evidence.fetch_id
            )
        )
        if fetch_id_existing is not None:
            raise ImmutableEvidenceConflict("authority raw fetch_id was reused with new content")
        record = AuthorityRawFetchEvidence(
            fetch_id=evidence.fetch_id,
            provider_id=evidence.provider_id,
            domain=evidence.domain.value,
            logical_endpoint=evidence.logical_endpoint,
            parameters=dict(evidence.parameters),
            requested_at=evidence.requested_at,
            received_at=evidence.received_at,
            content_hash=evidence.content_hash,
            schema_version=evidence.schema_version,
            normalization_version=evidence.normalization_version,
            source_timestamp=evidence.source_timestamp,
            snapshot_identity=evidence.snapshot_identity,
            storage_reference=evidence.storage_reference,
            immutable_identity=evidence.immutable_identity,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def persist_dataset_snapshot(
        self, snapshot: ResearchDatasetSnapshot
    ) -> AuthorityDatasetSnapshotRecord:
        """Store a snapshot manifest once; same ID with new content is a conflict."""

        existing = self.session.scalar(
            select(AuthorityDatasetSnapshotRecord).where(
                AuthorityDatasetSnapshotRecord.snapshot_id == snapshot.snapshot_id
            )
        )
        if existing is not None:
            if existing.manifest_hash != snapshot.manifest_hash:
                raise ImmutableEvidenceConflict("authority dataset snapshot_id was reused")
            return existing
        record = AuthorityDatasetSnapshotRecord(
            snapshot_id=snapshot.snapshot_id,
            created_at=snapshot.created_at,
            data_cutoff=snapshot.data_cutoff,
            provider_versions=dict(snapshot.provider_versions),
            raw_hashes=dict(snapshot.raw_hashes),
            normalized_dataset_hashes=dict(snapshot.normalized_dataset_hashes),
            security_master_hash=snapshot.security_master_hash,
            corporate_action_hash=snapshot.corporate_action_hash,
            benchmark_hash=snapshot.benchmark_hash,
            fundamental_hash=snapshot.fundamental_hash,
            universe_hash=snapshot.universe_hash,
            schema_version=snapshot.schema_version,
            normalization_version=snapshot.normalization_version,
            git_sha=snapshot.git_sha,
            manifest_hash=snapshot.manifest_hash,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def persist_index_constituent(
        self, constituent: HistoricalIndexConstituent
    ) -> HistoricalIndexConstituentEvidence:
        """Append authoritative constituent evidence; current lists stay distinct."""

        content_hash = sha256(
            json.dumps(
                {
                    "index_id": constituent.index_id,
                    "security_id": constituent.security_id,
                    "effective_from": constituent.effective_from.isoformat(),
                    "effective_to": (
                        constituent.effective_to.isoformat()
                        if constituent.effective_to is not None
                        else None
                    ),
                    "announcement_time": (
                        constituent.announcement_time.isoformat()
                        if constituent.announcement_time is not None
                        else None
                    ),
                    "known_at": constituent.known_at.isoformat(),
                    "source": constituent.source,
                    "source_record_id": constituent.source_record_id,
                    "confidence": constituent.confidence,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        existing = self.session.scalar(
            select(HistoricalIndexConstituentEvidence).where(
                HistoricalIndexConstituentEvidence.index_id == constituent.index_id,
                HistoricalIndexConstituentEvidence.security_id == constituent.security_id,
                HistoricalIndexConstituentEvidence.effective_from == constituent.effective_from,
                HistoricalIndexConstituentEvidence.source == constituent.source,
                HistoricalIndexConstituentEvidence.source_record_id == constituent.source_record_id,
            )
        )
        if existing is not None:
            if existing.content_hash != content_hash:
                raise ImmutableEvidenceConflict("index constituent source record content changed")
            return existing
        record = HistoricalIndexConstituentEvidence(
            index_id=constituent.index_id,
            security_id=constituent.security_id,
            effective_from=constituent.effective_from,
            effective_to=constituent.effective_to,
            announcement_time=constituent.announcement_time,
            known_at=constituent.known_at,
            source=constituent.source,
            source_record_id=constituent.source_record_id,
            confidence=Decimal(str(constituent.confidence)),
            content_hash=content_hash,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def persist_provider_conflict(
        self, conflict: ProviderValueConflict
    ) -> AuthorityProviderConflictRecord:
        """Keep unresolved conflicts durable rather than choosing a backtest winner."""

        conflict_id = sha256(
            "|".join(
                (
                    conflict.domain.value,
                    conflict.entity_id,
                    conflict.effective_at.isoformat(),
                    conflict.provider_a,
                    conflict.provider_b,
                    str(conflict.value_a),
                    str(conflict.value_b),
                )
            ).encode("utf-8")
        ).hexdigest()
        existing = self.session.scalar(
            select(AuthorityProviderConflictRecord).where(
                AuthorityProviderConflictRecord.conflict_id == conflict_id
            )
        )
        if existing is not None:
            return existing
        record = AuthorityProviderConflictRecord(
            conflict_id=conflict_id,
            domain=conflict.domain.value,
            entity_id=conflict.entity_id,
            effective_at=conflict.effective_at,
            provider_a=conflict.provider_a,
            provider_b=conflict.provider_b,
            value_a=str(conflict.value_a),
            value_b=str(conflict.value_b),
            tolerance=str(conflict.tolerance),
            resolution=conflict.resolution.value,
            resolved_provider=conflict.resolved_provider,
            reason=conflict.reason,
            quality_status=conflict.quality_status.value,
        )
        self.session.add(record)
        self.session.flush()
        return record

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
