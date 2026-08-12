# Historical Text / Event Corpus Certification

Date: 2026-08-12

Result: **NOT_CERTIFIABLE**

## 1. Real Corpus State

Current database:

- `intelligence_raw_information`: `0`
- `intelligence_events`: `0`
- `intelligence_event_evidence`: `0`

No SEC filing, earnings release, transcript, company announcement, or news
historical corpus is installed.

## 2. Raw Information Schema

`RawInformation` now supports:

- `raw_id`
- `document_id`
- `source`
- `source_identifier`
- `permanent_security_id`
- `ticker_as_of`
- `document_type`
- `title`
- `body`
- `timezone`
- `source_url`
- `source_hash`
- `ingestion_version`
- `published_at`
- `filed_at`
- `accepted_at`
- `event_time`
- `provider_received_at`
- `available_at`
- `processed_at`
- `revision_id`
- `decision_as_of`
- `data_cutoff`

The PIT invariant remains:

`available_at <= decision_as_of`

## 3. Immutable Raw Layer

`RawInformation` source checksum is derived from immutable source identity, raw
payload, and publication identity. Revisions are separate records with their own
`revision_id`, `available_at`, and checksum.

The corpus certification rejects:

- overwritten raw payloads
- missing source checksum
- missing availability
- missing timezone
- missing revision identity for multi-version documents
- future documents at the certification cutoff
- future total-return or revision metadata

## 4. SEC Provider

`SecEdgarImmutablePackageProvider` is implemented as a local immutable SEC EDGAR
package loader. It accepts JSONL `RawInformation` records and requires forms:

- `10-K`
- `10-Q`
- `8-K`

It does not call the network, and it does not accept LLM summaries as raw
evidence.

## 5. Earnings Release Contract

`TextCorpusSourceKind.EARNINGS_RELEASE` and `TextCorpusSource` define the
provider contract for earnings releases. No earnings-release corpus or provider
data package is currently installed.

## 6. Corpus Manifest

`HistoricalTextCorpusManifest` includes:

- `corpus_id`
- `sources`
- `provider_version`
- `coverage_start`
- `coverage_end`
- `symbol_count`
- `document_count`
- `revision_count`
- `duplicate_count`
- `document_type_counts`
- `missingness`
- `availability_complete`
- `raw_content_hash`
- `extraction_coverage`
- `certification_state`
- `blockers`
- `manifest_hash`

## 7. Certification Rules

`PIT_TEXT_CERTIFIED` requires:

- non-empty corpus
- source identity
- immutable payload checksum
- availability timestamp
- timezone
- symbol mapping
- revision history
- no future documents at cutoff
- no duplicates
- replay safety

Otherwise the state is `NOT_CERTIFIABLE`.

## 8. Runnable Command

```text
python scripts/run_text_corpus_certification.py \
  --root path/to/raw-jsonl \
  --source path/to/source-contract.json \
  --corpus-id historical-sec \
  --cutoff 2026-08-11T20:30:00+00:00 \
  --required-start 2018-07-03 \
  --required-end 2026-08-11 \
  --output var/research-data/text-corpus
```

## 9. Verification

- Ruff: `PASS`
- strict mypy: `PASS`, 368 source files
- pytest: `680 passed`
- secret scan: to be rerun after docs
- synthetic `TEST_ONLY` corpus runner: `PIT_TEXT_CERTIFIED`

## 10. Blocking Evidence

1. No historical SEC filing corpus.
2. No historical earnings-release corpus.
3. No earnings-call transcript corpus.
4. No company-announcement corpus.
5. No news/event-feed corpus.
6. No document coverage dates.
7. No symbols.
8. No extraction coverage.

The infrastructure is ready for an immutable, PIT-timestamped text corpus. The
system remains fail-closed until real corpus data is supplied and certified.

## 11. Round 2.5B Update

This round adds the official SEC EDGAR acquisition layer:

- `src/personal_alpha_terminal/intelligence/sec_edgar_acquisition.py`
- `scripts/run_sec_edgar_acquisition.py`
- `config/research/sec_edgar_source_contract.json`
- `config/research/cik_manifest.example.json`

The SEC client refuses to run without `SEC_USER_AGENT`, enforces a conservative
rate limit, handles retries and `Retry-After`, and writes immutable raw filing
payloads plus `acquisition.json` and `documents.jsonl`.

Real acquisition status: **NOT RUN**

Reason:

`SEC_USER_AGENT_REQUIRED`

No certified CIK-to-security mapping exists because the market research dataset
is still blocked.

The empty-corpus runner produced:

`NOT_CERTIFIABLE`

See:

- `docs/SEC_EDGAR_ACQUISITION_REPORT.md`
- `docs/SEC_EDGAR_INTEGRATION_GUIDE.md`

## 12. Round 2.5B Extension

The corpus model now supports non-ticker SEC identity:

- `CIK + accession` as raw identity
- `issuer_id` on `RawInformation`
- `amended_document_id` and amendment revisions
- `ACQUIRED` / `PIT_SOURCE_CERTIFIED` / `SECURITY_MAPPING_PENDING` /
  `PIT_TEXT_CERTIFIED` / `NOT_CERTIFIABLE` states
- issuer, mapped/unmapped security, amendment, and mapping completeness counts
  in `HistoricalTextCorpusManifest`
- `SEC_AVAILABILITY_POLICY_V1`

`LLM_RESEARCH_DATA_DEPENDENCY = SECURITY_MAPPING_PENDING`

No real corpus exists, so certification remains:

`NOT_CERTIFIABLE`
