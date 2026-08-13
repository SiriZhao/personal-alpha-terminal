import gzip
import io
import json
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from personal_alpha_terminal.intelligence.factor_registry import (
    CrossSectionalEventFactorEngine,
    default_llm_factor_registry,
)
from personal_alpha_terminal.intelligence.historical_replay import (
    HistoricalAIReplay,
    HistoricalAIReplayStatus,
)
from personal_alpha_terminal.intelligence.sec_edgar_acquisition import (
    CikSecurityMapping,
    EdgarFilingRecord,
    SecEdgarAcquisitionConfig,
    SecEdgarAvailabilityMissing,
    SecEdgarClient,
    SecEdgarHttpError,
    SecEdgarRateLimiter,
    SecEdgarUserAgentRequired,
    acquire_company_corpus,
    build_raw_information,
    load_cik_mapping_manifest,
    parse_edgar_submissions,
    verify_sec_edgar_landing_zone,
)
from personal_alpha_terminal.intelligence.text_corpus import (
    SecEdgarImmutablePackageProvider,
    TextCorpusSource,
    TextCorpusSourceKind,
    TextCorpusState,
    certify_text_corpus,
)


def _source() -> TextCorpusSource:
    return TextCorpusSource(
        source_id="sec-edgar",
        source_kind=TextCorpusSourceKind.SEC_FILING,
        provider="sec-edgar-immutable",
        availability_timestamp_proven=True,
        revision_history=True,
        symbol_mapping=True,
        timezone=True,
        raw_payload_immutable=True,
        rate_limit_compliant=True,
        coverage_start=date(2018, 7, 3),
        coverage_end=date(2026, 8, 11),
    )


def _mapping() -> CikSecurityMapping:
    return CikSecurityMapping(
        cik=320193,
        permanent_security_id="SEC-AAPL",
        ticker_as_of="AAPL",
        mapping_source_type="HISTORICAL_TIMELINE",
        source_identity="certified-market-dataset-hash",
        available_at=datetime(2018, 7, 3, tzinfo=UTC),
    )


def _submissions_payload() -> dict[str, object]:
    return {
        "cik": "0000320193",
        "name": "Apple Inc.",
        "filings": {
            "recent": [
                {
                    "accessionNumber": "0000320193-24-000001",
                    "form": "10-Q",
                    "filingDate": "2024-01-05",
                    "reportDate": "2023-12-30",
                    "primaryDocument": "aapl-20240105.htm",
                    "primaryDocDescription": "Quarterly Report",
                    "acceptanceDateTime": "2024-01-05T16:10:00-05:00",
                },
                {
                    "accessionNumber": "0000320193-24-000002",
                    "form": "8-K",
                    "filingDate": "2024-01-06",
                    "reportDate": "2024-01-05",
                    "primaryDocument": "aapl-20240106.htm",
                    "primaryDocDescription": "Current Report",
                    "acceptanceDateTime": "2024-01-06T16:11:00-05:00",
                },
                {
                    "accessionNumber": "0000320193-24-000003",
                    "form": "SC 13D",
                    "filingDate": "2024-01-06",
                    "primaryDocument": "sc13d.htm",
                },
                {
                    "accessionNumber": "0000320193-24-000004",
                    "form": "10-K",
                    "filingDate": "2025-01-06",
                    "primaryDocument": "aapl-20250106.htm",
                },
            ]
        },
    }


def _opener(
    payload: dict[str, object] | None = None,
    raw_text: str | None = None,
) -> object:
    submissions = json.dumps(payload or _submissions_payload()).encode("utf-8")
    body = (raw_text or "IMMUTABLE SEC RAW PAYLOAD").encode("utf-8")

    def open(request: Request) -> io.BytesIO:
        if "submissions/CIK" in request.full_url:
            return io.BytesIO(submissions)
        return io.BytesIO(body)

    return open


def _columnar_submissions_payload() -> dict[str, object]:
    return {
        "cik": "0001318605",
        "name": "Tesla, Inc.",
        "filings": {
            "recent": {
                "acceptanceDateTime": [
                    "2025-01-30T01:42:33Z",
                    "2025-04-30T21:08:56Z",
                ],
                "accessionNumber": [
                    "0001628280-25-003063",
                    "0001104659-25-042659",
                ],
                "filingDate": ["2025-01-30", "2025-04-30"],
                "form": ["10-K", "10-K/A"],
                "primaryDocDescription": ["Annual Report", "Amended Annual Report"],
                "primaryDocument": ["tsla-20241231.htm", "tm252787d2_10ka.htm"],
                "reportDate": ["2024-12-31", "2024-12-31"],
            }
        },
    }


class _HeaderResponse(io.BytesIO):
    def __init__(self, body: bytes, headers: dict[str, str]) -> None:
        super().__init__(body)
        self.headers = headers


def _record(
    *,
    accession: str,
    form: str = "10-Q",
    acceptance: datetime | None = None,
    amended_accession: str | None = None,
) -> EdgarFilingRecord:
    return EdgarFilingRecord(
        cik=320193,
        company_name="Apple Inc.",
        form_type=form,
        accession_number=accession,
        filing_date=acceptance.date() if acceptance else date(2024, 1, 5),
        report_date=date(2023, 12, 30),
        primary_document="aapl.htm",
        primary_doc_description=None,
        acceptance_datetime=acceptance,
        amended_accession=amended_accession,
    )


def test_sec_user_agent_is_required() -> None:
    with pytest.raises(SecEdgarUserAgentRequired):
        SecEdgarAcquisitionConfig(user_agent="missing-contact")


def test_parse_edgar_submissions_filters_forms_and_coverage() -> None:
    records = parse_edgar_submissions(
        _submissions_payload(),
        cik=320193,
        required_start=date(2024, 1, 1),
        required_end=date(2024, 12, 31),
    )
    assert [item.form_type for item in records] == ["10-Q", "8-K"]
    assert records[0].acceptance_datetime is not None
    assert records[0].document_url.endswith("aapl-20240105.htm")


def test_build_raw_information_uses_acceptance_time_and_keeps_mapping() -> None:
    payload = parse_edgar_submissions(
        _submissions_payload(),
        cik=320193,
        required_start=date(2024, 1, 1),
        required_end=date(2024, 12, 31),
    )[0]
    raw = build_raw_information(
        payload,
        "IMMUTABLE RAW",
        mapping=_mapping(),
        ingested_at=datetime(2024, 1, 7, tzinfo=UTC),
    )
    assert raw.document_type == "10-Q"
    assert raw.permanent_security_id == "SEC-AAPL"
    assert raw.ticker_as_of == "AAPL"
    assert raw.available_at == payload.acceptance_datetime
    assert raw.visible_at(payload.acceptance_datetime) is True
    assert raw.visible_at(datetime(2024, 1, 1, tzinfo=UTC)) is False


def test_missing_acceptance_is_rejected_and_reported() -> None:
    record = EdgarFilingRecord(
        cik=320193,
        company_name="Apple Inc.",
        form_type="10-K",
        accession_number="0000320193-24-000004",
        filing_date=date(2025, 1, 6),
        report_date=date(2024, 12, 31),
        primary_document="aapl-20250106.htm",
        primary_doc_description=None,
        acceptance_datetime=None,
    )
    with pytest.raises(SecEdgarAvailabilityMissing):
        build_raw_information(
            record,
            "raw",
            mapping=None,
            ingested_at=datetime(2025, 1, 7, tzinfo=UTC),
        )


def test_acquire_company_corpus_writes_immutable_raw_landing_zone(
    tmp_path: Path,
) -> None:
    config = SecEdgarAcquisitionConfig(user_agent="Test Company research@example.invalid")
    client = SecEdgarClient(
        config,
        rate_limiter=SecEdgarRateLimiter(max_requests_per_second=10),
        opener=_opener(),  # type: ignore[arg-type]
    )
    output = tmp_path / "landing" / "acq-1"
    report = acquire_company_corpus(
        cik=320193,
        mapping=_mapping(),
        config=config,
        client=client,
        source=_source(),
        output=output,
        acquisition_id="acq-1",
        required_start=date(2024, 1, 1),
        required_end=date(2024, 12, 31),
        max_documents=10,
        provider_version="sec-edgar-v1",
    )
    assert report.acquired_document_count == 2
    assert report.status == "ACQUIRED"
    assert report.blockers == ()
    assert (output / "acquisition.json").exists()
    assert json.loads((output / "checkpoint.json").read_text(encoding="utf-8"))["complete"]
    assert (output / "documents.jsonl").exists()
    raw_files = tuple((output / "320193").glob("*/raw.txt"))
    assert len(raw_files) == 2
    metadata_files = tuple((output / "320193").glob("*/metadata.json"))
    assert len(metadata_files) == 2

    before = (output / "acquisition.json").read_text(encoding="utf-8")
    repeated = acquire_company_corpus(
        cik=320193,
        mapping=_mapping(),
        config=config,
        client=client,
        source=_source(),
        output=output,
        acquisition_id="acq-1",
        required_start=date(2024, 1, 1),
        required_end=date(2024, 12, 31),
        max_documents=10,
        provider_version="sec-edgar-v1",
    )
    assert repeated.acquired_document_count == 2
    assert (output / "acquisition.json").read_text(encoding="utf-8") == before


def test_acquire_company_corpus_blocks_missing_mapping_and_acceptance(
    tmp_path: Path,
) -> None:
    payload = _submissions_payload()
    filings = payload["filings"]
    assert isinstance(filings, dict)
    recent = filings["recent"]
    assert isinstance(recent, list)
    recent[0] = {
        **recent[0],
        "acceptanceDateTime": None,
    }
    config = SecEdgarAcquisitionConfig(user_agent="Test Company research@example.invalid")
    client = SecEdgarClient(
        config,
        rate_limiter=SecEdgarRateLimiter(max_requests_per_second=10),
        opener=_opener(payload=payload),  # type: ignore[arg-type]
    )
    output = tmp_path / "landing" / "partial"
    report = acquire_company_corpus(
        cik=320193,
        mapping=None,
        config=config,
        client=client,
        source=_source(),
        output=output,
        acquisition_id="partial",
        required_start=date(2024, 1, 1),
        required_end=date(2024, 12, 31),
        max_documents=10,
        provider_version="sec-edgar-v1",
    )
    assert report.status == "PARTIAL"
    assert report.skipped_missing_acceptance == 1
    assert report.missing_security_mapping_count == 1
    assert "SEC_ACCEPTANCE_TIMESTAMPS_MISSING" in report.blockers
    assert "SEC_SECURITY_MAPPING_MISSING" in report.blockers


def test_cik_mapping_manifest_rejects_current_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "cik.json"
    path.write_text(
        json.dumps(
            {
                "source_identity": "current-snapshot",
                "mappings": [
                    {
                        "cik": 320193,
                        "permanent_security_id": "SEC-X",
                        "ticker_as_of": "AAPL",
                        "mapping_source_type": "CURRENT_SNAPSHOT",
                        "available_at": "2024-01-06T00:00:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="current CIK/ticker snapshot"):
        load_cik_mapping_manifest(path)


def test_immutable_sec_provider_accepts_typed_sec_forms(tmp_path: Path) -> None:
    from personal_alpha_terminal.intelligence.schemas import RawInformation

    observed = datetime(2024, 1, 5, 16, tzinfo=UTC)
    raw = RawInformation(
        raw_id="sec-1",
        source="sec-edgar",
        source_identifier="accession-1",
        title="SEC 8-K",
        body="immutable body",
        permanent_security_id="SEC-AAPL",
        ticker_as_of="AAPL",
        document_type="SEC_8K",
        timezone="America/New_York",
        published_at=observed,
        observed_at=observed,
        ingested_at=observed,
        data_cutoff=observed,
        available_at=observed,
        revision_id="r1",
    )
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "documents.jsonl").write_text(raw.model_dump_json() + "\n", encoding="utf-8")
    provider = SecEdgarImmutablePackageProvider(
        provider_version="sec-edgar-v1",
        source=_source(),
    )
    documents = provider.load(root)
    assert len(documents) == 1
    assert documents[0].document_type == "SEC_8K"


def test_sec_client_retries_rate_limit_and_handles_403() -> None:
    config = SecEdgarAcquisitionConfig(
        user_agent="Test Company research@example.invalid",
        max_retries=1,
        retry_backoff_seconds=0,
    )
    attempts: list[int] = []
    rate_error = HTTPError(
        "https://data.sec.gov/test",
        429,
        "Too Many Requests",
        {"Retry-After": "0"},
        None,
    )

    def retry_opener(request: Request) -> io.BytesIO:
        attempts.append(1)
        if len(attempts) == 1:
            raise rate_error
        return io.BytesIO(b"ok")

    client = SecEdgarClient(config, opener=retry_opener)  # type: ignore[arg-type]
    assert client.fetch_text("https://data.sec.gov/test") == "ok"
    assert len(attempts) == 2

    forbidden = HTTPError(
        "https://data.sec.gov/test",
        403,
        "Forbidden",
        {},
        None,
    )

    def forbidden_opener(request: Request) -> io.BytesIO:
        raise forbidden

    blocked = SecEdgarClient(config, opener=forbidden_opener)  # type: ignore[arg-type]
    with pytest.raises(SecEdgarHttpError, match="HTTP 403"):
        blocked.fetch_text("https://data.sec.gov/test")


def test_stage1_unmapped_acquisition_is_preserved(tmp_path: Path) -> None:
    config = SecEdgarAcquisitionConfig(
        user_agent="Test Company research@example.invalid",
    )
    client = SecEdgarClient(
        config,
        rate_limiter=SecEdgarRateLimiter(max_requests_per_second=10),
        opener=_opener(),  # type: ignore[arg-type]
    )
    output = tmp_path / "landing" / "stage1"
    report = acquire_company_corpus(
        cik=320193,
        mapping=None,
        config=config,
        client=client,
        source=_source(),
        output=output,
        acquisition_id="stage1",
        required_start=date(2024, 1, 1),
        required_end=date(2024, 12, 31),
        max_documents=10,
        provider_version="sec-edgar-v1",
    )
    assert report.status == "ACQUIRED_NOT_FULLY_MAPPED"
    assert report.mapped_document_count == 0
    assert report.unmapped_document_count == 2
    assert report.issuer_count == 1
    assert "SEC_SECURITY_MAPPING_MISSING" in report.blockers


def test_filing_metadata_separates_acceptance_and_local_retrieval(
    tmp_path: Path,
) -> None:
    config = SecEdgarAcquisitionConfig(
        user_agent="Test Company research@example.invalid",
    )
    client = SecEdgarClient(
        config,
        rate_limiter=SecEdgarRateLimiter(max_requests_per_second=10),
        opener=_opener(),  # type: ignore[arg-type]
    )
    output = tmp_path / "landing" / "metadata"
    acquire_company_corpus(
        cik=320193,
        mapping=_mapping(),
        config=config,
        client=client,
        source=_source(),
        output=output,
        acquisition_id="metadata",
        required_start=date(2024, 1, 1),
        required_end=date(2024, 12, 31),
        max_documents=10,
        provider_version="sec-edgar-v1",
    )
    metadata_path = next((output / "320193").glob("*/metadata.json"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    acceptance = datetime.fromisoformat(str(metadata["acceptance_datetime"]))
    retrieval = datetime.fromisoformat(str(metadata["retrieval_timestamp"]))
    assert retrieval > acceptance
    raw_path = metadata_path.with_name("raw.txt")
    assert sha256(raw_path.read_bytes()).hexdigest() == metadata["raw_payload_sha256"]
    assert metadata["normalization_version"] == "sec-edgar-normalization-v1"


def test_landing_zone_detects_corrupted_raw_file(tmp_path: Path) -> None:
    config = SecEdgarAcquisitionConfig(
        user_agent="Test Company research@example.invalid",
    )
    client = SecEdgarClient(
        config,
        rate_limiter=SecEdgarRateLimiter(max_requests_per_second=10),
        opener=_opener(),  # type: ignore[arg-type]
    )
    output = tmp_path / "landing" / "corrupt"
    acquire_company_corpus(
        cik=320193,
        mapping=_mapping(),
        config=config,
        client=client,
        source=_source(),
        output=output,
        acquisition_id="corrupt",
        required_start=date(2024, 1, 1),
        required_end=date(2024, 12, 31),
        max_documents=10,
        provider_version="sec-edgar-v1",
    )
    raw_path = next((output / "320193").glob("*/raw.txt"))
    raw_path.write_text("tampered", encoding="utf-8")
    verification = verify_sec_edgar_landing_zone(output)
    assert verification.ok is False
    assert any("SEC_RAW_CHECKSUM_MISMATCH" in item for item in verification.blockers)


def test_amendment_groups_with_original_and_is_pit_visible() -> None:
    original_time = datetime(2024, 1, 5, 16, tzinfo=UTC)
    amendment_time = original_time + timedelta(days=2)
    original = _record(
        accession="0000320193-24-000001",
        acceptance=original_time,
    )
    amendment = _record(
        accession="0000320193-24-000002",
        form="10-Q/A",
        acceptance=amendment_time,
        amended_accession=original.accession_number,
    )
    ingested = amendment_time + timedelta(hours=1)
    original_raw = build_raw_information(
        original,
        "original body",
        mapping=_mapping(),
        ingested_at=ingested,
    )
    amendment_raw = build_raw_information(
        amendment,
        "amendment body",
        mapping=_mapping(),
        ingested_at=ingested,
    )
    assert original_raw.document_id == amendment_raw.document_id
    assert amendment_raw.amended_document_id == original_raw.document_id
    assert amendment_raw.revision_id.startswith("amendment-")

    replay = HistoricalAIReplay(
        CrossSectionalEventFactorEngine(default_llm_factor_registry())
    )
    early = replay.run(
        cutoff=original_time + timedelta(hours=1),
        documents=(original_raw, amendment_raw),
        events=(),
        eligible_symbols=("AAPL",),
        sector_by_symbol={"AAPL": "TECH"},
        market_data_certified=True,
        text_data_certified=True,
    )
    late = replay.run(
        cutoff=amendment_time + timedelta(hours=1),
        documents=(original_raw, amendment_raw),
        events=(),
        eligible_symbols=("AAPL",),
        sector_by_symbol={"AAPL": "TECH"},
        market_data_certified=True,
        text_data_certified=True,
    )
    assert early.status is HistoricalAIReplayStatus.READY
    assert early.visible_document_ids == (original_raw.raw_id,)
    assert late.visible_document_ids == (original_raw.raw_id, amendment_raw.raw_id)
    assert early.replay_hash != late.replay_hash


def test_corpus_manifest_counts_issuers_mapping_and_amendments() -> None:
    original_time = datetime(2024, 1, 5, 16, tzinfo=UTC)
    amendment_time = original_time + timedelta(days=2)
    original = _record(accession="0000320193-24-000001", acceptance=original_time)
    amendment = _record(
        accession="0000320193-24-000002",
        form="10-Q/A",
        acceptance=amendment_time,
        amended_accession=original.accession_number,
    )
    ingested = amendment_time + timedelta(hours=1)
    original_raw = build_raw_information(
        original,
        "original body",
        mapping=_mapping(),
        ingested_at=ingested,
    )
    amendment_raw = build_raw_information(
        amendment,
        "amendment body",
        mapping=_mapping(),
        ingested_at=ingested,
    )
    manifest = certify_text_corpus(
        (original_raw, amendment_raw),
        (),
        corpus_id="sec-amendment",
        sources=(_source(),),
        cutoff=ingested,
    )
    assert manifest.certification_state is TextCorpusState.PIT_TEXT_CERTIFIED
    assert manifest.issuer_count == 1
    assert manifest.mapped_security_count == 1
    assert manifest.unmapped_issuer_count == 0
    assert manifest.amendment_count == 1
    assert manifest.revision_count == 2
    assert manifest.mapping_completeness == 1.0


def test_mapping_pending_corpus_is_not_full_certified() -> None:
    accepted = datetime(2024, 1, 5, 16, tzinfo=UTC)
    record = _record(
        accession="0000320193-24-000001",
        acceptance=accepted,
    )
    raw = build_raw_information(
        record,
        "unmapped body",
        mapping=None,
        ingested_at=accepted + timedelta(hours=1),
    )
    manifest = certify_text_corpus(
        (raw,),
        (),
        corpus_id="sec-unmapped",
        sources=(_source(),),
        cutoff=accepted + timedelta(hours=1),
    )
    assert manifest.certification_state is TextCorpusState.SECURITY_MAPPING_PENDING
    assert "SYMBOL_MAPPING_INCOMPLETE" in manifest.blockers
    assert manifest.unmapped_issuer_count == 1
    assert manifest.mapping_completeness == 0.0


def test_deterministic_source_hash_for_same_filing_payload() -> None:
    accepted = datetime(2024, 1, 5, 16, tzinfo=UTC)
    record = _record(accession="0000320193-24-000001", acceptance=accepted)
    ingested = accepted + timedelta(hours=1)
    first = build_raw_information(
        record,
        "same raw body",
        mapping=_mapping(),
        ingested_at=ingested,
    )
    second = build_raw_information(
        record,
        "same raw body",
        mapping=_mapping(),
        ingested_at=ingested,
    )
    assert first.source_hash == second.source_hash


def test_sec_client_retries_5xx() -> None:
    config = SecEdgarAcquisitionConfig(
        user_agent="Test Company research@example.invalid",
        max_retries=1,
        retry_backoff_seconds=0,
    )
    attempts: list[int] = []
    server_error = HTTPError(
        "https://data.sec.gov/test",
        503,
        "Service Unavailable",
        {"Retry-After": "0"},
        None,
    )

    def opener(request: Request) -> io.BytesIO:
        attempts.append(1)
        if len(attempts) == 1:
            raise server_error
        return io.BytesIO(b"ok")

    client = SecEdgarClient(config, opener=opener)  # type: ignore[arg-type]
    assert client.fetch_text("https://data.sec.gov/test") == "ok"
    assert len(attempts) == 2


def test_sec_client_decodes_gzip_response() -> None:
    config = SecEdgarAcquisitionConfig(user_agent="Test Company research@example.invalid")

    def opener(request: Request) -> _HeaderResponse:
        del request
        return _HeaderResponse(gzip.compress(b"gzip response ok"), {"Content-Encoding": "gzip"})

    client = SecEdgarClient(config, opener=opener)  # type: ignore[arg-type]
    assert client.fetch_text("https://data.sec.gov/test") == "gzip response ok"


def test_parse_edgar_submissions_supports_current_columnar_shape() -> None:
    records = parse_edgar_submissions(
        _columnar_submissions_payload(),
        cik=1318605,
        required_start=date(2025, 1, 1),
        required_end=date(2025, 4, 30),
    )
    assert [item.form_type for item in records] == ["10-K", "10-K/A"]
    assert records[1].amended_accession == records[0].accession_number


def test_parse_edgar_submissions_binds_amendment_to_latest_original() -> None:
    payload = _columnar_submissions_payload()
    filings = payload["filings"]
    assert isinstance(filings, dict)
    recent = filings["recent"]
    assert isinstance(recent, dict)
    recent["accessionNumber"] = [
        "0001628280-25-003063",
        "0001628280-25-003064",
        "0001104659-25-042659",
    ]
    recent["form"] = ["10-K", "10-K", "10-K/A"]
    recent["filingDate"] = ["2025-01-30", "2025-01-31", "2025-04-30"]
    recent["reportDate"] = ["2024-12-31", "2024-12-31", "2024-12-31"]
    recent["primaryDocument"] = ["original.htm", "second.htm", "amendment.htm"]
    recent["acceptanceDateTime"] = [
        "2025-01-30T01:42:33Z",
        "2025-01-31T01:42:33Z",
        "2025-04-30T21:08:56Z",
    ]
    recent["primaryDocDescription"] = ["Annual", "Annual", "Amended Annual"]
    records = parse_edgar_submissions(
        payload,
        cik=1318605,
        required_start=date(2025, 1, 1),
        required_end=date(2025, 4, 30),
    )
    amendment = records[-1]
    assert amendment.form_type == "10-K/A"
    assert amendment.amended_accession == "0001628280-25-003064"


def test_raw_archive_preserves_lf_and_checksum(tmp_path: Path) -> None:
    raw_text = "line1\nline2\nline3\n"
    config = SecEdgarAcquisitionConfig(user_agent="Test Company research@example.invalid")
    client = SecEdgarClient(
        config,
        rate_limiter=SecEdgarRateLimiter(max_requests_per_second=10),
        opener=_opener(raw_text=raw_text),  # type: ignore[arg-type]
    )
    output = tmp_path / "landing" / "lf"
    acquire_company_corpus(
        cik=320193,
        mapping=_mapping(),
        config=config,
        client=client,
        source=_source(),
        output=output,
        acquisition_id="lf",
        required_start=date(2024, 1, 1),
        required_end=date(2024, 12, 31),
        max_documents=10,
        provider_version="sec-edgar-v1",
    )
    raw_path = next((output / "320193").glob("*/raw.txt"))
    assert raw_path.read_bytes() == raw_text.encode("utf-8")
    metadata = json.loads(raw_path.with_name("metadata.json").read_text(encoding="utf-8"))
    assert sha256(raw_path.read_bytes()).hexdigest() == metadata["raw_payload_sha256"]


def test_acquire_corpus_resumes_without_overwriting_existing(tmp_path: Path) -> None:
    config = SecEdgarAcquisitionConfig(user_agent="Test Company research@example.invalid")
    client = SecEdgarClient(
        config,
        rate_limiter=SecEdgarRateLimiter(max_requests_per_second=10),
        opener=_opener(),  # type: ignore[arg-type]
    )
    output = tmp_path / "landing" / "resume"
    first = acquire_company_corpus(
        cik=320193,
        mapping=_mapping(),
        config=config,
        client=client,
        source=_source(),
        output=output,
        acquisition_id="resume",
        required_start=date(2024, 1, 1),
        required_end=date(2024, 12, 31),
        max_documents=1,
        provider_version="sec-edgar-v1",
    )
    first_raw = next((output / "320193").glob("*/raw.txt"))
    first_bytes = first_raw.read_bytes()
    first_manifest = (output / "acquisition.json").read_bytes()
    second = acquire_company_corpus(
        cik=320193,
        mapping=_mapping(),
        config=config,
        client=client,
        source=_source(),
        output=output,
        acquisition_id="resume",
        required_start=date(2024, 1, 1),
        required_end=date(2024, 12, 31),
        max_documents=2,
        provider_version="sec-edgar-v1",
    )
    assert first.acquired_document_count == 1
    assert second.acquired_document_count == 2
    assert first_raw.read_bytes() == first_bytes
    assert (output / "acquisition.json").read_bytes() == first_manifest
    assert second.manifest_path is not None
    assert second.manifest_path.name != "acquisition.json"
    assert len(tuple((output / "320193").glob("*/raw.txt"))) == 2


def test_retry_after_is_capped_at_configuration_limit() -> None:
    config = SecEdgarAcquisitionConfig(
        user_agent="Test Company research@example.invalid",
        max_retry_after_seconds=2.0,
    )
    client = SecEdgarClient(config)
    error = HTTPError(
        "https://data.sec.gov/test",
        429,
        "Too Many Requests",
        {"Retry-After": "3600"},
        None,
    )
    assert client._retry_delay(error, 0) == 2.0
