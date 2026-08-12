"""Provider-neutral historical text/event corpus certification and replay input.

The corpus layer only certifies immutable raw text with PIT availability.  It
does not turn LLM extraction, web-scraped snapshots, or LLM memory into
historical evidence.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.intelligence.schemas import RawInformation, UnifiedEvent, _aware


class TextDocumentType(StrEnum):
    SEC_10K = "SEC_10K"
    SEC_10Q = "SEC_10Q"
    SEC_8K = "SEC_8K"
    EARNINGS_RELEASE = "EARNINGS_RELEASE"
    EARNINGS_TRANSCRIPT = "EARNINGS_TRANSCRIPT"
    COMPANY_ANNOUNCEMENT = "COMPANY_ANNOUNCEMENT"
    NEWS = "NEWS"
    OTHER = "OTHER"


class TextCorpusSourceKind(StrEnum):
    SEC_FILING = "SEC_FILING"
    EARNINGS_RELEASE = "EARNINGS_RELEASE"
    EARNINGS_TRANSCRIPT = "EARNINGS_TRANSCRIPT"
    COMPANY_ANNOUNCEMENT = "COMPANY_ANNOUNCEMENT"
    NEWS = "NEWS"


class TextCorpusState(StrEnum):
    ACQUIRED = "ACQUIRED"
    PIT_SOURCE_CERTIFIED = "PIT_SOURCE_CERTIFIED"
    SECURITY_MAPPING_PENDING = "SECURITY_MAPPING_PENDING"
    PIT_TEXT_CERTIFIED = "PIT_TEXT_CERTIFIED"
    NOT_CERTIFIABLE = "NOT_CERTIFIABLE"


@dataclass(frozen=True, slots=True)
class TextCorpusSource:
    source_id: str
    source_kind: TextCorpusSourceKind
    provider: str
    availability_timestamp_proven: bool
    revision_history: bool
    symbol_mapping: bool
    timezone: bool
    raw_payload_immutable: bool
    rate_limit_compliant: bool
    coverage_start: date | None = None
    coverage_end: date | None = None
    known_limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.provider.strip():
            raise ValueError("text corpus source identity is incomplete")

    def document(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(json.dumps(asdict(self), default=str)))


@dataclass(frozen=True, slots=True)
class HistoricalTextCorpusManifest:
    corpus_id: str
    schema_version: str
    provider_version: str
    sources: tuple[TextCorpusSource, ...]
    coverage_start: date | None
    coverage_end: date | None
    symbol_count: int
    document_count: int
    revision_count: int
    duplicate_count: int
    document_type_counts: dict[str, int]
    missingness: float
    availability_complete: bool
    raw_content_hash: str
    extraction_coverage: float
    certification_state: TextCorpusState
    blockers: tuple[str, ...]
    manifest_hash: str
    issuer_count: int = 0
    mapped_security_count: int = 0
    unmapped_issuer_count: int = 0
    amendment_count: int = 0
    mapping_completeness: float = 1.0

    def document(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            json.loads(json.dumps(asdict(self), default=str, sort_keys=True)),
        )


class TextCorpusProvider(Protocol):
    provider_id: str
    provider_version: str
    source: TextCorpusSource

    def load(self, root: Path) -> tuple[RawInformation, ...]: ...


class SecEdgarImmutablePackageProvider:
    """Load local immutable SEC EDGAR raw packages without calling the network.

    The loader accepts JSONL files containing validated `RawInformation`.  It
    does not fetch from EDGAR, and it does not accept summaries as raw evidence.
    """

    provider_id = "sec-edgar-immutable"
    SEC_FORM_TYPES = {
        "10-K",
        "10-Q",
        "8-K",
        "10-K/A",
        "10-Q/A",
        "8-K/A",
        "SEC_10K",
        "SEC_10Q",
        "SEC_8K",
        "SEC_10K/A",
        "SEC_10Q/A",
        "SEC_8K/A",
    }

    def __init__(
        self,
        *,
        provider_version: str,
        source: TextCorpusSource,
    ) -> None:
        if source.source_kind is not TextCorpusSourceKind.SEC_FILING:
            raise ValueError("SEC EDGAR provider requires SEC_FILING source kind")
        self.provider_version = provider_version
        self.source = source

    def load(self, root: Path) -> tuple[RawInformation, ...]:
        documents: list[RawInformation] = []
        for path in sorted(root.rglob("*.jsonl")) if root.exists() else ():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                document = RawInformation.model_validate_json(line)
                normalized_type = str(document.document_type or "").upper()
                if normalized_type not in self.SEC_FORM_TYPES:
                    raise ValueError(f"SEC package contains unsupported form: {normalized_type}")
                documents.append(document)
        return tuple(documents)


def certify_text_corpus(
    documents: tuple[RawInformation, ...],
    events: tuple[UnifiedEvent, ...],
    *,
    corpus_id: str,
    sources: tuple[TextCorpusSource, ...],
    cutoff: datetime,
    required_start: date | None = None,
    required_end: date | None = None,
    provider_version: str = "",
) -> HistoricalTextCorpusManifest:
    """Certify raw text/event corpus for historical PIT replay."""

    _aware(cutoff, "corpus cutoff")
    blockers: list[str] = []
    if not corpus_id.strip():
        blockers.append("TEXT_CORPUS_ID_MISSING")
    if not documents:
        blockers.append("HISTORICAL_TEXT_CORPUS_MISSING")
    if not sources:
        blockers.append("TEXT_CORPUS_SOURCE_IDENTITY_MISSING")

    source_by_id = {item.source_id: item for item in sources}
    for source in sources:
        if not source.availability_timestamp_proven:
            blockers.append("SOURCE_AVAILABILITY_TIMESTAMP_NOT_PROVEN")
        if not source.revision_history:
            blockers.append("SOURCE_REVISION_HISTORY_NOT_PROVEN")
        if not source.symbol_mapping:
            blockers.append("SOURCE_SYMBOL_MAPPING_NOT_PROVEN")
        if not source.timezone:
            blockers.append("SOURCE_TIMEZONE_NOT_PROVEN")
        if not source.raw_payload_immutable:
            blockers.append("SOURCE_RAW_PAYLOAD_NOT_IMMUTABLE")
        if not source.rate_limit_compliant:
            blockers.append("SOURCE_RATE_LIMIT_NOT_COMPLIANT")
    visible_documents = tuple(item for item in documents if item.visible_at(cutoff))
    if len(visible_documents) != len(documents):
        blockers.append("FUTURE_DOCUMENT_AT_CERTIFICATION_CUTOFF")

    mapped = 0
    revision_documents = 0
    availability_complete = True
    unique_versions: set[tuple[str, str, str]] = set()
    document_type_counts: dict[str, int] = {}
    issuer_ids: set[str] = set()
    mapped_security_ids: set[str] = set()
    unmapped_issuer_ids: set[str] = set()
    amendment_count = 0

    for document in documents:
        issuer_id = document.issuer_id
        if issuer_id:
            issuer_ids.add(issuer_id)
            if document.permanent_security_id:
                mapped_security_ids.add(document.permanent_security_id)
            else:
                unmapped_issuer_ids.add(issuer_id)
        if _is_amendment(document):
            amendment_count += 1
            if not document.amended_document_id:
                blockers.append("AMENDMENT_ORIGINAL_IDENTITY_MISSING")
        if not document.document_id:
            blockers.append("DOCUMENT_ID_MISSING")
        if not document.source_hash:
            blockers.append("RAW_DOCUMENT_CHECKSUM_MISSING")
        if document.available_at is None:
            blockers.append("DOCUMENT_AVAILABILITY_MISSING")
            availability_complete = False
        if not document.timezone:
            blockers.append("DOCUMENT_TIMEZONE_MISSING")
            availability_complete = False
        if document.source not in source_by_id:
            blockers.append("DOCUMENT_SOURCE_NOT_IN_CORPUS")
            continue
        source = source_by_id[document.source]
        if source.symbol_mapping and (
            not document.permanent_security_id or not document.ticker_as_of
        ):
            blockers.append("SYMBOL_MAPPING_INCOMPLETE")
        else:
            mapped += 1
        if source.raw_payload_immutable and not document.source_hash:
            blockers.append("RAW_PAYLOAD_NOT_IMMUTABLE")
        if source.timezone and not document.timezone:
            blockers.append("SOURCE_REQUIRES_DOCUMENT_TIMEZONE")
        document_type_counts[str(document.document_type or "UNKNOWN")] = (
            document_type_counts.get(str(document.document_type or "UNKNOWN"), 0) + 1
        )
        unique_versions.add(
            (
                _document_group_id(document),
                document.revision_id or "",
                document.source_hash or "",
            )
        )

    by_document_id: dict[str, list[RawInformation]] = {}
    for document in documents:
        by_document_id.setdefault(_document_group_id(document), []).append(document)
    for versions in by_document_id.values():
        if len(versions) <= 1:
            continue
        revision_documents += len(versions)
        if any(item.revision_id is None for item in versions):
            blockers.append("REVISION_ID_MISSING")
        ordered = sorted(versions, key=lambda item: item.available_at or item.observed_at)
        if any(
            left.available_at is not None
            and right.available_at is not None
            and right.available_at < left.available_at
            for left, right in zip(ordered, ordered[1:], strict=False)
        ):
            blockers.append("REVISION_CHRONOLOGY_INVALID")

    date_values = tuple(
        sorted(
            item.available_at.date()
            for item in documents
            if item.available_at is not None and item.available_at <= cutoff
        )
    )
    coverage_start = date_values[0] if date_values else None
    coverage_end = date_values[-1] if date_values else None
    if required_start is not None and (coverage_start is None or coverage_start > required_start):
        blockers.append("TEXT_CORPUS_START_COVERAGE_INCOMPLETE")
    if required_end is not None and (coverage_end is None or coverage_end < required_end):
        blockers.append("TEXT_CORPUS_END_COVERAGE_INCOMPLETE")

    duplicate_count = max(0, len(documents) - len(unique_versions))
    if duplicate_count:
        blockers.append("DUPLICATE_DOCUMENT_VERSION")
    symbol_count = len(
        {item.permanent_security_id for item in documents if item.permanent_security_id}
    )
    mapped_security_count = len(mapped_security_ids)
    unmapped_issuer_count = len(unmapped_issuer_ids)
    mapping_completeness = (
        mapped_security_count / len(issuer_ids) if issuer_ids else 1.0
    )
    missingness = 1.0 - (mapped / len(documents) if documents else 0.0)
    raw_content_hash = fingerprint(
        tuple(
            sorted(
                (
                    _document_group_id(item),
                    item.revision_id or "",
                    item.source_hash or "",
                )
                for item in documents
            )
        )
    )
    extraction_source_hashes = {
        evidence.source_hash
        for event in events
        for evidence in event.evidence
    }
    extraction_coverage = (
        len(extraction_source_hashes) / len(documents) if documents else 0.0
    )
    mapping_blockers = {
        "SYMBOL_MAPPING_INCOMPLETE",
        "SOURCE_SYMBOL_MAPPING_NOT_PROVEN",
    }
    non_mapping_blockers = tuple(item for item in blockers if item not in mapping_blockers)
    state = (
        TextCorpusState.NOT_CERTIFIABLE
        if non_mapping_blockers
        else TextCorpusState.SECURITY_MAPPING_PENDING
        if blockers
        else TextCorpusState.PIT_TEXT_CERTIFIED
    )
    manifest = HistoricalTextCorpusManifest(
        corpus_id=corpus_id,
        schema_version="historical-text-corpus-v1",
        provider_version=provider_version,
        sources=sources,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        symbol_count=symbol_count,
        document_count=len(documents),
        revision_count=revision_documents,
        duplicate_count=duplicate_count,
        document_type_counts=document_type_counts,
        missingness=missingness,
        availability_complete=availability_complete,
        raw_content_hash=raw_content_hash,
        extraction_coverage=extraction_coverage,
        certification_state=state,
        blockers=tuple(dict.fromkeys(blockers)),
        manifest_hash="",
        issuer_count=len(issuer_ids),
        mapped_security_count=mapped_security_count,
        unmapped_issuer_count=unmapped_issuer_count,
        amendment_count=amendment_count,
        mapping_completeness=mapping_completeness,
    )
    manifest_hash = _manifest_hash(manifest)
    return _replace_hash(manifest, manifest_hash)


def persist_text_corpus_manifest(
    manifest: HistoricalTextCorpusManifest,
    root: Path,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{manifest.manifest_hash}.json"
    rendered = json.dumps(
        manifest.document(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if target.exists() and target.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite immutable text corpus: {target}")
    target.write_text(rendered, encoding="utf-8")
    return target


def _replace_hash(
    manifest: HistoricalTextCorpusManifest,
    manifest_hash: str,
) -> HistoricalTextCorpusManifest:
    return HistoricalTextCorpusManifest(
        corpus_id=manifest.corpus_id,
        schema_version=manifest.schema_version,
        provider_version=manifest.provider_version,
        sources=manifest.sources,
        coverage_start=manifest.coverage_start,
        coverage_end=manifest.coverage_end,
        symbol_count=manifest.symbol_count,
        document_count=manifest.document_count,
        revision_count=manifest.revision_count,
        duplicate_count=manifest.duplicate_count,
        document_type_counts=manifest.document_type_counts,
        missingness=manifest.missingness,
        availability_complete=manifest.availability_complete,
        raw_content_hash=manifest.raw_content_hash,
        extraction_coverage=manifest.extraction_coverage,
        certification_state=manifest.certification_state,
        blockers=manifest.blockers,
        manifest_hash=manifest_hash,
        issuer_count=manifest.issuer_count,
        mapped_security_count=manifest.mapped_security_count,
        unmapped_issuer_count=manifest.unmapped_issuer_count,
        amendment_count=manifest.amendment_count,
        mapping_completeness=manifest.mapping_completeness,
    )


def _manifest_hash(manifest: HistoricalTextCorpusManifest) -> str:
    document = manifest.document()
    document.pop("manifest_hash", None)
    return fingerprint(document)


def _document_group_id(document: RawInformation) -> str:
    return document.amended_document_id or document.document_id or document.raw_id


def _is_amendment(document: RawInformation) -> bool:
    normalized = str(document.document_type or "").upper()
    return normalized.endswith("/A") or document.amended_document_id is not None
