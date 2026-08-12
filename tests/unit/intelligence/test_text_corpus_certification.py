from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from personal_alpha_terminal.intelligence.cache import extraction_cache_key
from personal_alpha_terminal.intelligence.factor_registry import (
    CrossSectionalEventFactorEngine,
    default_llm_factor_registry,
)
from personal_alpha_terminal.intelligence.historical_replay import (
    HistoricalAIReplay,
    HistoricalAIReplayStatus,
)
from personal_alpha_terminal.intelligence.schemas import RawInformation
from personal_alpha_terminal.intelligence.text_corpus import (
    TextCorpusSource,
    TextCorpusSourceKind,
    TextCorpusState,
    certify_text_corpus,
)

NEW_YORK = ZoneInfo("America/New_York")
PUBLISHED = datetime(2024, 1, 5, 16, tzinfo=NEW_YORK)


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
    )


def _document(
    *,
    raw_id: str = "doc-1",
    document_id: str | None = None,
    published_at: datetime = PUBLISHED,
    revision_id: str | None = "r1",
    timezone: str | None = "America/New_York",
    permanent_security_id: str | None = "SEC-AAPL",
    ticker_as_of: str | None = "AAPL",
    source_identifier: str | None = None,
    body: str | None = None,
) -> RawInformation:
    observed = published_at + timedelta(minutes=1)
    ingested = observed + timedelta(minutes=1)
    available = observed
    return RawInformation(
        raw_id=raw_id,
        document_id=document_id or raw_id,
        source="sec-edgar",
        source_identifier=source_identifier or f"accession-{raw_id}",
        title="SEC filing",
        body=body or f"Immutable raw payload {raw_id}",
        permanent_security_id=permanent_security_id,
        ticker_as_of=ticker_as_of,
        document_type="SEC_8K",
        timezone=timezone,
        ingestion_version="1",
        published_at=published_at,
        observed_at=observed,
        ingested_at=ingested,
        data_cutoff=ingested,
        available_at=available,
        revision_id=revision_id,
        decision_as_of=ingested,
    )


def test_empty_corpus_is_not_certifiable() -> None:
    manifest = certify_text_corpus(
        (),
        (),
        corpus_id="historical-sec",
        sources=(_source(),),
        cutoff=PUBLISHED + timedelta(days=1),
    )
    assert manifest.certification_state is TextCorpusState.NOT_CERTIFIABLE
    assert "HISTORICAL_TEXT_CORPUS_MISSING" in manifest.blockers


def test_complete_pit_corpus_certifies() -> None:
    document = _document()
    manifest = certify_text_corpus(
        (document,),
        (),
        corpus_id="historical-sec",
        sources=(_source(),),
        cutoff=document.data_cutoff,
    )
    assert manifest.certification_state is TextCorpusState.PIT_TEXT_CERTIFIED
    assert manifest.document_count == 1
    assert manifest.symbol_count == 1
    assert manifest.availability_complete is True
    assert manifest.missingness == 0.0
    assert manifest.raw_content_hash
    assert manifest.manifest_hash


def test_future_revision_is_excluded_and_replay_hash_is_invariant() -> None:
    cutoff = PUBLISHED + timedelta(hours=1)
    visible = _document()
    future = _document(
        raw_id="doc-future",
        document_id="doc-1",
        published_at=PUBLISHED + timedelta(days=2),
        revision_id="r2",
    )
    manifest = certify_text_corpus(
        (visible, future),
        (),
        corpus_id="historical-sec",
        sources=(_source(),),
        cutoff=cutoff,
    )
    assert manifest.certification_state is TextCorpusState.NOT_CERTIFIABLE
    assert "FUTURE_DOCUMENT_AT_CERTIFICATION_CUTOFF" in manifest.blockers

    replay = HistoricalAIReplay(CrossSectionalEventFactorEngine(default_llm_factor_registry()))
    baseline = replay.run(
        cutoff=cutoff,
        documents=(visible,),
        events=(),
        eligible_symbols=("AAPL",),
        sector_by_symbol={"AAPL": "TECH"},
        market_data_certified=True,
        text_data_certified=True,
    )
    changed = replay.run(
        cutoff=cutoff,
        documents=(visible, future),
        events=(),
        eligible_symbols=("AAPL",),
        sector_by_symbol={"AAPL": "TECH"},
        market_data_certified=True,
        text_data_certified=True,
    )
    assert baseline.status is HistoricalAIReplayStatus.READY
    assert changed.visible_document_ids == baseline.visible_document_ids
    assert changed.replay_hash == baseline.replay_hash


def test_same_document_multi_version_replay_is_temporal() -> None:
    v1 = _document(raw_id="doc-v1", document_id="doc-1", revision_id="r1")
    v2 = _document(
        raw_id="doc-v2",
        document_id="doc-1",
        published_at=PUBLISHED + timedelta(hours=2),
        revision_id="r2",
    )
    replay = HistoricalAIReplay(CrossSectionalEventFactorEngine(default_llm_factor_registry()))
    early = replay.run(
        cutoff=PUBLISHED + timedelta(hours=1),
        documents=(v1, v2),
        events=(),
        eligible_symbols=("AAPL",),
        sector_by_symbol={"AAPL": "TECH"},
        market_data_certified=True,
        text_data_certified=True,
    )
    late = replay.run(
        cutoff=PUBLISHED + timedelta(hours=3),
        documents=(v1, v2),
        events=(),
        eligible_symbols=("AAPL",),
        sector_by_symbol={"AAPL": "TECH"},
        market_data_certified=True,
        text_data_certified=True,
    )
    assert early.visible_document_ids == ("doc-v1",)
    assert late.visible_document_ids == ("doc-v1", "doc-v2")
    assert early.visible_document_versions == ("doc-1|r1|doc-v1",)
    assert late.visible_document_versions == (
        "doc-1|r1|doc-v1",
        "doc-1|r2|doc-v2",
    )
    assert early.replay_hash != late.replay_hash


def test_missing_timezone_and_symbol_mapping_block_certification() -> None:
    missing_metadata = _document(timezone=None, permanent_security_id=None, ticker_as_of=None)
    manifest = certify_text_corpus(
        (missing_metadata,),
        (),
        corpus_id="historical-sec",
        sources=(_source(),),
        cutoff=missing_metadata.data_cutoff,
    )
    assert manifest.certification_state is TextCorpusState.NOT_CERTIFIABLE
    assert "DOCUMENT_TIMEZONE_MISSING" in manifest.blockers
    assert "SYMBOL_MAPPING_INCOMPLETE" in manifest.blockers


def test_duplicate_document_version_is_detected() -> None:
    first = _document()
    duplicate = _document(
        raw_id="doc-duplicate",
        document_id="doc-1",
        source_identifier=first.source_identifier,
        body=first.body,
    )
    manifest = certify_text_corpus(
        (first, duplicate),
        (),
        corpus_id="historical-sec",
        sources=(_source(),),
        cutoff=first.data_cutoff,
    )
    assert manifest.duplicate_count == 1
    assert "DUPLICATE_DOCUMENT_VERSION" in manifest.blockers


def test_extraction_cache_identity_includes_model_and_prompt() -> None:
    first = extraction_cache_key("hash-a", "deepseek-v4-flash", "event-extraction-v2")
    changed_model = extraction_cache_key("hash-a", "deepseek-v4-pro", "event-extraction-v2")
    changed_prompt = extraction_cache_key("hash-a", "deepseek-v4-flash", "event-extraction-v3")
    assert len({first, changed_model, changed_prompt}) == 3


def test_source_contract_flags_must_be_proven_before_certification() -> None:
    document = _document()
    unproven = replace(
        _source(),
        availability_timestamp_proven=False,
        revision_history=False,
    )
    manifest = certify_text_corpus(
        (document,),
        (),
        corpus_id="historical-sec",
        sources=(unproven,),
        cutoff=document.data_cutoff,
    )
    assert manifest.certification_state is TextCorpusState.NOT_CERTIFIABLE
    assert "SOURCE_AVAILABILITY_TIMESTAMP_NOT_PROVEN" in manifest.blockers
    assert "SOURCE_REVISION_HISTORY_NOT_PROVEN" in manifest.blockers


def test_amendment_without_linked_original_is_not_certified() -> None:
    document = _document().model_copy(
        update={
            "raw_id": "unbound-amendment",
            "document_id": "unbound-amendment",
            "document_type": "10-Q/A",
            "amended_document_id": None,
            "revision_id": "amendment-unbound",
        }
    )
    manifest = certify_text_corpus(
        (document,),
        (),
        corpus_id="unbound-amendment",
        sources=(_source(),),
        cutoff=document.data_cutoff,
    )
    assert manifest.certification_state is TextCorpusState.NOT_CERTIFIABLE
    assert "AMENDMENT_ORIGINAL_IDENTITY_MISSING" in manifest.blockers
