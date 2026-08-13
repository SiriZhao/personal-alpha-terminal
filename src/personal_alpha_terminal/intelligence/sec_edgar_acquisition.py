"""Official SEC EDGAR historical acquisition with immutable PIT raw evidence.

The module never sends requests unless a compliant declared User-Agent is
provided through ``SEC_USER_AGENT``.  It keeps raw filing payloads immutable,
records availability from SEC acceptance metadata, and leaves corpus
certification and DeepSeek extraction to the existing text corpus layer.
"""

from __future__ import annotations

import gzip
import json
import time
import zlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, BinaryIO, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.intelligence.schemas import RawInformation
from personal_alpha_terminal.intelligence.text_corpus import TextCorpusSource

SEC_EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_EDGAR_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_document}"
_BASE_SEC_FORM_TYPES = ("10-K", "10-Q", "8-K", "6-K", "20-F", "40-F", "DEF 14A", "4")
SEC_FORM_TYPES = frozenset(
    (*_BASE_SEC_FORM_TYPES, *(f"{form}/A" for form in _BASE_SEC_FORM_TYPES))
)
SEC_AVAILABILITY_POLICY_V1 = "SEC_AVAILABILITY_POLICY_V1"
SEC_NORMALIZATION_VERSION = "sec-edgar-normalization-v1"


class SecEdgarAcquisitionError(RuntimeError):
    """Base class for SEC acquisition failures."""


class SecEdgarUserAgentRequired(SecEdgarAcquisitionError):
    """Raised when no compliant SEC_USER_AGENT is available."""


class SecEdgarHttpError(SecEdgarAcquisitionError):
    """Raised for HTTP or network failures after retries are exhausted."""


class SecEdgarMalformedPayload(SecEdgarAcquisitionError):
    """Raised when EDGAR JSON does not match the documented shape."""


class SecEdgarAvailabilityMissing(SecEdgarAcquisitionError):
    """Raised when a filing cannot be assigned an exact availability time."""


class SecEdgarLandingZoneCorrupt(SecEdgarAcquisitionError):
    """Raised when an existing immutable SEC archive is incomplete or changed."""


@dataclass(frozen=True, slots=True)
class SecEdgarAcquisitionConfig:
    user_agent: str
    timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
    max_retry_after_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.user_agent.strip() or "@" not in self.user_agent:
            raise SecEdgarUserAgentRequired(
                "SEC_USER_AGENT must be a declared contact like 'Company Name admin@example.com'"
            )
        if self.timeout_seconds <= 0:
            raise ValueError("SEC timeout must be positive")
        if self.max_retries < 0:
            raise ValueError("SEC retry count cannot be negative")
        if self.retry_backoff_seconds < 0 or self.max_retry_after_seconds < 0:
            raise ValueError("SEC retry delays cannot be negative")


class SecEdgarRateLimiter:
    """Conservative project-level pacing below the official SEC limit."""

    def __init__(self, max_requests_per_second: float = 1.0) -> None:
        if max_requests_per_second <= 0 or max_requests_per_second > 10:
            raise ValueError("SEC rate limit must be between 0 and 10 requests/second")
        self.min_interval_seconds = 1.0 / max_requests_per_second
        self._last_request_at = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delay = self.min_interval_seconds - (now - self._last_request_at)
        if delay > 0:
            time.sleep(delay)
        self._last_request_at = time.monotonic()


@dataclass(frozen=True, slots=True)
class EdgarFilingRecord:
    cik: int
    company_name: str
    form_type: str
    accession_number: str
    filing_date: date
    report_date: date | None
    primary_document: str
    primary_doc_description: str | None
    acceptance_datetime: datetime | None
    amended_accession: str | None = None

    def __post_init__(self) -> None:
        if self.cik <= 0:
            raise ValueError("CIK must be positive")
        if not self.company_name.strip() or not self.accession_number.strip():
            raise ValueError("filing identity is incomplete")
        if self.form_type not in SEC_FORM_TYPES:
            raise ValueError(f"unsupported SEC form: {self.form_type}")
        if not self.primary_document.strip():
            raise ValueError("SEC filing has no primary document")
        if self.acceptance_datetime is not None:
            if (
                self.acceptance_datetime.tzinfo is None
                or self.acceptance_datetime.utcoffset() is None
            ):
                raise ValueError("SEC acceptance datetime must be timezone-aware")

    @property
    def accession_number_no_dashes(self) -> str:
        return self.accession_number.replace("-", "")

    @property
    def document_url(self) -> str:
        return SEC_EDGAR_ARCHIVE.format(
            cik=self.cik,
            accession_no_dashes=self.accession_number_no_dashes,
            primary_document=self.primary_document,
        )


@dataclass(frozen=True, slots=True)
class CikSecurityMapping:
    cik: int
    permanent_security_id: str
    ticker_as_of: str
    mapping_source_type: str
    source_identity: str
    available_at: datetime
    source_version: str | None = None

    def __post_init__(self) -> None:
        if self.cik <= 0:
            raise ValueError("CIK must be positive")
        if not self.permanent_security_id.strip() or not self.ticker_as_of.strip():
            raise ValueError("CIK security mapping is incomplete")
        if self.mapping_source_type.upper() == "CURRENT_SNAPSHOT":
            raise ValueError("current CIK/ticker snapshot cannot map historical filings")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("CIK security mapping available_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class SecEdgarFilingMetadata:
    cik: int
    accession_number: str
    form: str
    filing_date: date
    acceptance_datetime: datetime
    reporting_period_end: date | None
    issuer_name: str
    source_identity: str
    source_url: str
    retrieval_timestamp: datetime
    raw_payload_sha256: str
    normalized_sha256: str
    local_archive_path: str
    normalization_version: str
    amended_accession: str | None
    document_id: str
    revision_id: str
    availability_policy: str

    def document(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            json.loads(json.dumps(asdict(self), default=str, sort_keys=True)),
        )


@dataclass(frozen=True, slots=True)
class SecEdgarLandingZoneVerification:
    ok: bool
    blockers: tuple[str, ...]


class SecEdgarClient:
    """Rate-limited SEC EDGAR client with retry and Retry-After handling."""

    def __init__(
        self,
        config: SecEdgarAcquisitionConfig,
        *,
        rate_limiter: SecEdgarRateLimiter | None = None,
        opener: Callable[[Request], BinaryIO] | None = None,
    ) -> None:
        self.config = config
        self.rate_limiter = rate_limiter
        self._opener = opener or self._default_open

    def fetch_json(self, url: str) -> dict[str, Any]:
        payload = self._fetch(url)
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise SecEdgarMalformedPayload("SEC EDGAR JSON response is not an object")
        return parsed

    def fetch_text(self, url: str) -> str:
        return self._fetch(url)

    def _fetch(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "User-Agent": self.config.user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
        )
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            if self.rate_limiter is not None:
                self.rate_limiter.wait()
            try:
                response = self._opener(request)
                try:
                    raw = response.read()
                    headers = getattr(response, "headers", None)
                    content_encoding = (
                        headers.get("Content-Encoding", "").lower() if headers is not None else ""
                    )
                    if content_encoding == "gzip":
                        raw = gzip.decompress(raw)
                    elif content_encoding == "deflate":
                        try:
                            raw = zlib.decompress(raw)
                        except zlib.error:
                            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                    return raw.decode("utf-8")
                finally:
                    response.close()
            except HTTPError as error:
                if error.code in {429, 500, 502, 503, 504} and attempt < self.config.max_retries:
                    delay = self._retry_delay(error, attempt)
                    time.sleep(delay)
                    last_error = error
                    continue
                raise SecEdgarHttpError(
                    f"SEC EDGAR HTTP {error.code} for {url}"
                ) from error
            except URLError as error:
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_backoff_seconds * (2**attempt))
                    last_error = error
                    continue
                raise SecEdgarHttpError(f"SEC EDGAR network failure for {url}") from error
        raise SecEdgarHttpError(f"SEC EDGAR request failed for {url}") from last_error

    def _retry_delay(self, error: HTTPError, attempt: int) -> float:
        raw = error.headers.get("Retry-After") if error.headers else None
        if raw is not None and str(raw).strip().isdigit():
            retry_after = float(str(raw).strip())
            if retry_after > self.config.max_retry_after_seconds:
                return self.config.max_retry_after_seconds
            return retry_after
        return float(self.config.retry_backoff_seconds * (2**attempt))

    def _default_open(self, request: Request) -> BinaryIO:
        return cast(BinaryIO, urlopen(request, timeout=self.config.timeout_seconds))


def parse_edgar_submissions(
    payload: dict[str, Any],
    *,
    cik: int,
    required_start: date,
    required_end: date,
) -> tuple[EdgarFilingRecord, ...]:
    """Parse the official company submissions JSON and filter to frozen forms."""

    filings = payload.get("filings")
    if not isinstance(filings, dict):
        raise SecEdgarMalformedPayload("SEC EDGAR submissions missing filings object")
    recent = filings.get("recent")
    rows = _submission_rows(recent)
    company_name = str(payload.get("name") or "")
    records: list[EdgarFilingRecord] = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise SecEdgarMalformedPayload("SEC EDGAR filing row is not an object")
        form_type = str(raw.get("form") or "").upper()
        if form_type not in SEC_FORM_TYPES:
            continue
        accession = str(raw.get("accessionNumber") or "")
        filing_date = date.fromisoformat(str(raw.get("filingDate") or ""))
        if filing_date < required_start or filing_date > required_end:
            continue
        report_raw = raw.get("reportDate")
        report_date = date.fromisoformat(str(report_raw)) if report_raw else None
        primary = str(raw.get("primaryDocument") or "")
        description = raw.get("primaryDocDescription")
        description_value = str(description) if description else None
        acceptance = _parse_acceptance(raw.get("acceptanceDateTime"))
        if not accession or not primary:
            raise SecEdgarMalformedPayload("SEC EDGAR filing is missing accession or document")
        records.append(
            EdgarFilingRecord(
                cik=cik,
                company_name=company_name,
                form_type=form_type,
                accession_number=accession,
                filing_date=filing_date,
                report_date=report_date,
                primary_document=primary,
                primary_doc_description=description_value,
                acceptance_datetime=acceptance,
            )
        )
    return tuple(
        sorted(
            _bind_amendments(records),
            key=lambda item: (item.filing_date, item.accession_number),
        )
    )


def _bind_amendments(records: list[EdgarFilingRecord]) -> tuple[EdgarFilingRecord, ...]:
    """Bind an amendment to its latest prior original with matching report period.

    SEC submissions metadata does not expose the amended accession directly, so
    the parser uses the authoritative same-CIK form/reportDate/filingDate fields
    to identify the original revision.
    """

    bound: list[EdgarFilingRecord] = []
    for record in records:
        if not record.form_type.endswith("/A") or record.report_date is None:
            bound.append(record)
            continue
        base_form = record.form_type[:-2]
        candidates = tuple(
            item
            for item in records
            if item.form_type == base_form
            and item.report_date == record.report_date
            and (item.filing_date, item.accession_number)
            < (record.filing_date, record.accession_number)
        )
        if candidates:
            original = max(candidates, key=lambda item: (item.filing_date, item.accession_number))
            bound.append(replace(record, amended_accession=original.accession_number))
        else:
            bound.append(record)
    return tuple(bound)


def _submission_rows(recent: object) -> tuple[dict[str, object], ...]:
    """Normalize row-oriented or current column-oriented submissions JSON."""

    if isinstance(recent, list):
        return tuple(item for item in recent if isinstance(item, dict))
    if not isinstance(recent, dict):
        raise SecEdgarMalformedPayload("SEC EDGAR submissions missing recent filings")
    lengths = {len(value) for value in recent.values() if isinstance(value, list)}
    if not lengths:
        raise SecEdgarMalformedPayload("SEC EDGAR columnar recent filings are empty")
    if len(lengths) != 1:
        raise SecEdgarMalformedPayload("SEC EDGAR columnar recent filings have unequal lengths")
    columns = tuple(recent.items())
    keys = tuple(key for key, _ in columns)
    values_by_column = tuple(value for _, value in columns)
    return tuple(
        dict(zip(keys, values, strict=True))
        for values in zip(*values_by_column, strict=True)
    )


def _parse_acceptance(value: object) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/New_York"))
    return parsed


def build_raw_information(
    record: EdgarFilingRecord,
    raw_body: str,
    *,
    mapping: CikSecurityMapping | None,
    ingested_at: datetime,
) -> RawInformation:
    """Build an immutable RawInformation from SEC metadata and raw payload."""

    if record.acceptance_datetime is None:
        raise SecEdgarAvailabilityMissing(record.accession_number)
    acceptance = record.acceptance_datetime
    if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
        raise ValueError("SEC ingestion time must be timezone-aware")
    raw_id = f"sec-{record.cik}-{record.accession_number_no_dashes}"
    source_url = record.document_url
    if record.amended_accession:
        amended_document_id = f"sec-{record.cik}-{record.amended_accession.replace('-', '')}"
        document_id = amended_document_id
        revision_id = f"amendment-{record.accession_number_no_dashes}"
    else:
        amended_document_id = None
        document_id = raw_id
        revision_id = f"original-{record.accession_number_no_dashes}"
    return RawInformation(
        raw_id=raw_id,
        document_id=document_id,
        source="sec-edgar",
        source_identifier=record.accession_number,
        title=f"{record.company_name} {record.form_type} {record.accession_number}",
        body=raw_body,
        issuer_id=str(record.cik),
        issuer_name=record.company_name,
        issuer_resolution_status="ISSUER_RESOLVED",
        security_mapping_status="SECURITY_MAPPED" if mapping else "SECURITY_MAPPING_MISSING",
        security_mapping_source=mapping.source_identity if mapping else None,
        security_mapping_source_version=mapping.source_version if mapping else None,
        permanent_security_id=mapping.permanent_security_id if mapping else None,
        ticker_as_of=mapping.ticker_as_of if mapping else None,
        amended_document_id=amended_document_id,
        document_type=record.form_type,
        timezone="America/New_York",
        ingestion_version=SEC_NORMALIZATION_VERSION,
        published_at=acceptance,
        observed_at=acceptance,
        ingested_at=ingested_at,
        data_cutoff=ingested_at,
        source_url=source_url,
        filed_at=acceptance,
        accepted_at=acceptance,
        provider_received_at=acceptance,
        available_at=acceptance,
        processed_at=ingested_at,
        revision_id=revision_id,
        decision_as_of=ingested_at,
    )


@dataclass(frozen=True, slots=True)
class SecEdgarAcquisitionReport:
    acquisition_id: str
    provider_id: str
    provider_version: str
    cik: int
    requested_document_count: int
    acquired_document_count: int
    skipped_missing_acceptance: int
    failed_document_count: int
    failed_accessions: tuple[str, ...]
    missing_security_mapping_count: int
    retrieved_at: datetime
    raw_content_hash: str
    manifest_path: Path | None
    status: str
    blockers: tuple[str, ...]
    mapped_document_count: int = 0
    unmapped_document_count: int = 0
    amendment_count: int = 0
    issuer_count: int = 0
    availability_policy: str = SEC_AVAILABILITY_POLICY_V1

    def document(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            json.loads(json.dumps(asdict(self), default=str, sort_keys=True)),
        )


def acquire_company_corpus(
    *,
    cik: int,
    mapping: CikSecurityMapping | None,
    config: SecEdgarAcquisitionConfig,
    mapping_resolver: Callable[[EdgarFilingRecord], CikSecurityMapping | None] | None = None,
    client: SecEdgarClient,
    source: TextCorpusSource,
    output: Path,
    acquisition_id: str,
    required_start: date,
    required_end: date,
    max_documents: int,
    provider_version: str,
) -> SecEdgarAcquisitionReport:
    """Acquire one CIK's frozen SEC forms into an immutable raw landing zone."""

    if max_documents <= 0:
        raise ValueError("max_documents must be positive")
    output.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(UTC)
    submissions = client.fetch_json(SEC_EDGAR_SUBMISSIONS.format(cik=cik))
    records = parse_edgar_submissions(
        submissions,
        cik=cik,
        required_start=required_start,
        required_end=required_end,
    )[:max_documents]
    existing_documents = _read_document_jsonl(output / "documents.jsonl")
    existing_raw_ids = {item.raw_id for item in existing_documents}
    documents = list(existing_documents)
    skipped_missing_acceptance = 0
    failed_accessions: list[str] = []
    requested = 0

    for record in records:
        requested += 1
        record_mapping = mapping_resolver(record) if mapping_resolver is not None else mapping
        raw_id = f"sec-{record.cik}-{record.accession_number_no_dashes}"
        if raw_id in existing_raw_ids:
            continue
        if record.acceptance_datetime is None:
            skipped_missing_acceptance += 1
            continue
        filing_dir = output / str(record.cik) / record.accession_number_no_dashes
        if _existing_filing_archive_complete(filing_dir):
            raw_body = (filing_dir / "raw.txt").read_text(encoding="utf-8")
            raw = build_raw_information(
                record,
                raw_body,
                mapping=record_mapping,
                ingested_at=retrieved_at,
            )
        else:
            try:
                raw_body = client.fetch_text(record.document_url)
            except SecEdgarHttpError:
                failed_accessions.append(record.accession_number)
                continue
            raw = build_raw_information(
                record,
                raw_body,
                mapping=record_mapping,
                ingested_at=retrieved_at,
            )
            _persist_filing_archive(
                output,
                record,
                raw,
                raw_body,
                retrieved_at=retrieved_at,
            )
        documents.append(raw)
        existing_raw_ids.add(raw_id)
        _write_checkpoint(
            output / "checkpoint.json",
            acquisition_id=acquisition_id,
            cik=cik,
            completed_raw_ids=tuple(sorted(existing_raw_ids)),
            last_accession=record.accession_number,
        )

    sorted_documents = tuple(sorted(documents, key=lambda item: item.raw_id))
    existing_report = _read_existing_report(output / "acquisition.json")
    if existing_report is not None and len(documents) == len(existing_documents):
        return existing_report
    _write_document_jsonl(output / "documents.jsonl", sorted_documents)
    raw_content_hash = _raw_content_hash(sorted_documents, provider_version)
    mapped_document_count = sum(
        1 for item in sorted_documents if item.permanent_security_id
    )
    unmapped_document_count = len(sorted_documents) - mapped_document_count
    amendment_count = sum(
        1
        for item in sorted_documents
        if item.amended_document_id is not None
        or str(item.document_type or "").upper().endswith("/A")
    )
    issuer_count = len(
        {item.issuer_id for item in sorted_documents if item.issuer_id}
    )
    missing_mapping = unmapped_document_count if source.symbol_mapping else 0
    blockers: list[str] = []
    if skipped_missing_acceptance:
        blockers.append("SEC_ACCEPTANCE_TIMESTAMPS_MISSING")
    if failed_accessions:
        blockers.append("SEC_DOCUMENT_DOWNLOAD_FAILURES")
    if missing_mapping:
        blockers.append("SEC_SECURITY_MAPPING_MISSING")
    if skipped_missing_acceptance or failed_accessions:
        status = "PARTIAL"
    elif missing_mapping:
        status = "ACQUIRED_NOT_FULLY_MAPPED"
    else:
        status = "ACQUIRED"
    report = SecEdgarAcquisitionReport(
        acquisition_id=acquisition_id,
        provider_id="sec-edgar",
        provider_version=provider_version,
        cik=cik,
        requested_document_count=requested,
        acquired_document_count=len(sorted_documents),
        skipped_missing_acceptance=skipped_missing_acceptance,
        failed_document_count=len(failed_accessions),
        failed_accessions=tuple(failed_accessions),
        missing_security_mapping_count=missing_mapping,
        retrieved_at=retrieved_at,
        raw_content_hash=raw_content_hash,
        manifest_path=None,
        status=status,
        blockers=tuple(dict.fromkeys(blockers)),
        mapped_document_count=mapped_document_count,
        unmapped_document_count=unmapped_document_count,
        amendment_count=amendment_count,
        issuer_count=issuer_count,
        availability_policy=SEC_AVAILABILITY_POLICY_V1,
    )
    report = replace(report, manifest_path=_write_acquisition_manifest(output, report))
    _write_checkpoint(
        output / "checkpoint.json",
        acquisition_id=acquisition_id,
        cik=cik,
        completed_raw_ids=tuple(sorted(existing_raw_ids)),
        last_accession=records[-1].accession_number if records else None,
        complete=True,
    )
    return report


def _write_checkpoint(
    path: Path,
    *,
    acquisition_id: str,
    cik: int,
    completed_raw_ids: tuple[str, ...],
    last_accession: str | None,
    complete: bool = False,
) -> None:
    payload = {
        "acquisition_id": acquisition_id,
        "cik": cik,
        "completed_raw_ids": completed_raw_ids,
        "last_accession": last_accession,
        "complete": complete,
        "schema_version": "sec-acquisition-checkpoint-v1",
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    temporary.replace(path)


def _read_document_jsonl(path: Path) -> tuple[RawInformation, ...]:
    if not path.exists():
        return ()
    documents: list[RawInformation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            documents.append(RawInformation.model_validate_json(line))
    return tuple(documents)


def _existing_filing_archive_complete(filing_dir: Path) -> bool:
    return (filing_dir / "raw.txt").exists() and (filing_dir / "metadata.json").exists()


def _persist_filing_archive(
    output: Path,
    record: EdgarFilingRecord,
    raw: RawInformation,
    raw_body: str,
    *,
    retrieved_at: datetime,
) -> Path:
    filing_dir = output / str(record.cik) / record.accession_number_no_dashes
    raw_path = filing_dir / "raw.txt"
    metadata = _build_filing_metadata(
        record,
        raw,
        raw_body,
        local_archive_path=raw_path.relative_to(output).as_posix(),
        retrieved_at=retrieved_at,
    )
    _write_immutable_raw(raw_path, raw_body)
    metadata_path = filing_dir / "metadata.json"
    rendered_metadata = json.dumps(
        metadata.document(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if metadata_path.exists() and metadata_path.read_text(encoding="utf-8") != rendered_metadata:
        raise FileExistsError(
            f"refusing to overwrite immutable SEC metadata: {metadata_path}"
        )
    _atomic_write(metadata_path, rendered_metadata)
    submission_path = filing_dir / "submission.json"
    rendered_submission = json.dumps(
        asdict(record),
        ensure_ascii=False,
        default=str,
        indent=2,
        sort_keys=True,
    )
    if (
        submission_path.exists()
        and submission_path.read_text(encoding="utf-8") != rendered_submission
    ):
        raise FileExistsError(
            f"refusing to overwrite immutable SEC submission metadata: {submission_path}"
        )
    _atomic_write(submission_path, rendered_submission)
    return metadata_path


def _build_filing_metadata(
    record: EdgarFilingRecord,
    raw: RawInformation,
    raw_body: str,
    *,
    local_archive_path: str,
    retrieved_at: datetime,
) -> SecEdgarFilingMetadata:
    if record.acceptance_datetime is None:
        raise SecEdgarAvailabilityMissing(record.accession_number)
    return SecEdgarFilingMetadata(
        cik=record.cik,
        accession_number=record.accession_number,
        form=record.form_type,
        filing_date=record.filing_date,
        acceptance_datetime=record.acceptance_datetime,
        reporting_period_end=record.report_date,
        issuer_name=record.company_name,
        source_identity="https://www.sec.gov/Archives/edgar/data/",
        source_url=record.document_url,
        retrieval_timestamp=retrieved_at,
        raw_payload_sha256=sha256(raw_body.encode("utf-8")).hexdigest(),
        normalized_sha256=raw.source_hash or "",
        local_archive_path=local_archive_path,
        normalization_version=SEC_NORMALIZATION_VERSION,
        amended_accession=record.amended_accession,
        document_id=raw.document_id or raw.raw_id,
        revision_id=raw.revision_id or "",
        availability_policy=SEC_AVAILABILITY_POLICY_V1,
    )


def verify_sec_edgar_landing_zone(
    root: Path,
) -> SecEdgarLandingZoneVerification:
    """Verify immutable SEC raw files, metadata, and normalized checksums."""

    blockers: list[str] = []
    documents = _read_document_jsonl(root / "documents.jsonl")
    for document in documents:
        accession = str(document.source_identifier).replace("-", "")
        filing_dir = root / str(document.issuer_id or "UNKNOWN") / accession
        raw_path = filing_dir / "raw.txt"
        metadata_path = filing_dir / "metadata.json"
        if not raw_path.exists():
            blockers.append(f"SEC_RAW_FILE_MISSING:{document.raw_id}")
            continue
        if not metadata_path.exists():
            blockers.append(f"SEC_METADATA_FILE_MISSING:{document.raw_id}")
            continue
        try:
            metadata_document = cast(
                dict[str, object],
                json.loads(metadata_path.read_text(encoding="utf-8")),
            )
        except (OSError, ValueError) as error:
            blockers.append(
                f"SEC_METADATA_INVALID:{document.raw_id}:{type(error).__name__}"
            )
            continue
        raw_bytes = raw_path.read_bytes()
        expected_payload_hash = str(metadata_document.get("raw_payload_sha256") or "")
        if sha256(raw_bytes).hexdigest() != expected_payload_hash:
            blockers.append(f"SEC_RAW_CHECKSUM_MISMATCH:{document.raw_id}")
        normalized_hash = str(metadata_document.get("normalized_sha256") or "")
        if document.source_hash and normalized_hash != document.source_hash:
            blockers.append(f"SEC_NORMALIZED_CHECKSUM_MISMATCH:{document.raw_id}")
    if blockers:
        return SecEdgarLandingZoneVerification(False, tuple(dict.fromkeys(blockers)))
    return SecEdgarLandingZoneVerification(True, ())


def _read_existing_report(path: Path) -> SecEdgarAcquisitionReport | None:
    if not path.exists():
        return None
    document = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    manifest_value = document.get("manifest_path")
    return SecEdgarAcquisitionReport(
        acquisition_id=str(document["acquisition_id"]),
        provider_id=str(document["provider_id"]),
        provider_version=str(document["provider_version"]),
        cik=int(str(document["cik"])),
        requested_document_count=int(str(document["requested_document_count"])),
        acquired_document_count=int(str(document["acquired_document_count"])),
        skipped_missing_acceptance=int(str(document["skipped_missing_acceptance"])),
        failed_document_count=int(str(document["failed_document_count"])),
        failed_accessions=tuple(
            str(item) for item in cast(list[object], document["failed_accessions"])
        ),
        missing_security_mapping_count=int(
            str(document["missing_security_mapping_count"])
        ),
        retrieved_at=datetime.fromisoformat(str(document["retrieved_at"])),
        raw_content_hash=str(document["raw_content_hash"]),
        manifest_path=Path(str(manifest_value)) if manifest_value else None,
        status=str(document["status"]),
        blockers=tuple(str(item) for item in cast(list[object], document["blockers"])),
        mapped_document_count=int(str(document.get("mapped_document_count") or 0)),
        unmapped_document_count=int(str(document.get("unmapped_document_count") or 0)),
        amendment_count=int(str(document.get("amendment_count") or 0)),
        issuer_count=int(str(document.get("issuer_count") or 0)),
        availability_policy=str(
            document.get("availability_policy") or SEC_AVAILABILITY_POLICY_V1
        ),
    )


def _write_document_jsonl(path: Path, documents: tuple[RawInformation, ...]) -> None:
    rendered = "".join(
        item.model_dump_json() + "\n"
        for item in documents
    )
    _atomic_write(path, rendered)


def _write_immutable_raw(path: Path, content: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise FileExistsError(f"refusing to overwrite immutable SEC raw payload: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, content)


def _write_acquisition_manifest(
    output: Path, report: SecEdgarAcquisitionReport
) -> Path:
    target = output / "acquisition.json"
    rendered = json.dumps(
        report.document(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if target.exists() and target.read_text(encoding="utf-8") != rendered:
        versioned = output / f"acquisition-{sha256(rendered.encode('utf-8')).hexdigest()}.json"
        if versioned.exists() and versioned.read_text(encoding="utf-8") != rendered:
            raise FileExistsError(
                f"refusing to overwrite immutable SEC acquisition: {versioned}"
            )
        _atomic_write(versioned, rendered)
        return versioned
    _atomic_write(target, rendered)
    return target


def _raw_content_hash(
    documents: tuple[RawInformation, ...],
    provider_version: str,
    availability_policy: str = SEC_AVAILABILITY_POLICY_V1,
) -> str:
    return fingerprint(
        {
            "provider_version": provider_version,
            "availability_policy": availability_policy,
            "documents": tuple(
                (
                    item.raw_id,
                    item.document_id or item.raw_id,
                    item.revision_id or "",
                    item.source_hash or "",
                    item.issuer_id or "",
                    item.permanent_security_id or "",
                )
                for item in documents
            ),
        }
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)
    temporary.replace(path)


def load_cik_mapping_manifest(path: Path) -> tuple[CikSecurityMapping, ...]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("CIK mapping manifest must be a JSON object")
    entries = document.get("mappings")
    if not isinstance(entries, list):
        raise ValueError("CIK mapping manifest missing mappings list")
    source_identity = str(document.get("source_identity") or "")
    if not source_identity:
        raise ValueError("CIK mapping manifest missing source_identity")
    mappings: list[CikSecurityMapping] = []
    for raw in entries:
        if not isinstance(raw, dict):
            raise ValueError("CIK mapping entry must be an object")
        mappings.append(
            CikSecurityMapping(
                cik=int(str(raw["cik"])),
                permanent_security_id=str(raw["permanent_security_id"]),
                ticker_as_of=str(raw["ticker_as_of"]),
                mapping_source_type=str(raw["mapping_source_type"]),
                source_identity=source_identity,
                available_at=datetime.fromisoformat(str(raw["available_at"])),
            )
        )
    return tuple(sorted(mappings, key=lambda item: item.cik))
