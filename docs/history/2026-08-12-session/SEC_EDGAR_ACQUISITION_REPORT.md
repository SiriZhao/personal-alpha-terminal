# SEC EDGAR Historical Corpus Acquisition Report

Date: 2026-08-12

Result: **SEC_USER_AGENT_REQUIRED**

No real SEC corpus was fetched because no compliant `SEC_USER_AGENT` is
available in the environment. The code is implemented and tested, and the
official source contract is installed.

## 1. Source Authority

SEC official evidence:

- [Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- Current max request rate: 10 requests/second
- Declared bot User-Agent required
- EDGAR data starts in 1994/1995
- Post-acceptance corrections and deletions are documented
- CIKs are unique and not recycled

The project default rate limit is `1 request/second`, more conservative than
the official limit.

## 2. Real Corpus State

The real corpus remains empty:

- `intelligence_raw_information`: `0`
- `intelligence_events`: `0`
- `intelligence_event_evidence`: `0`

The runner executed with the empty corpus:

```text
python scripts/run_text_corpus_certification.py \
  --root var/research-data/raw/sec-edgar/not-installed \
  --source config/research/sec_edgar_source_contract.json \
  --corpus-id sec-edgar-empty \
  --cutoff 2026-08-11T20:30:00+00:00 \
  --required-start 2018-07-03 \
  --required-end 2026-08-11 \
  --provider-version sec-edgar-v1 \
  --output artifacts/latest/sec-edgar-corpus
```

Result:

`NOT_CERTIFIABLE`

Blockers:

- `HISTORICAL_TEXT_CORPUS_MISSING`
- `TEXT_CORPUS_START_COVERAGE_INCOMPLETE`
- `TEXT_CORPUS_END_COVERAGE_INCOMPLETE`

Artifact:

`artifacts/latest/sec-edgar-corpus/dacdb50e075de2b4ed84759a3244f815041ca9a3327cf893877580b055f69fae.json`

## 3. Acquisition Implementation

`src/personal_alpha_terminal/intelligence/sec_edgar_acquisition.py` now
provides:

- `SecEdgarAcquisitionConfig`
- `SecEdgarRateLimiter`
- `SecEdgarClient`
- retry / Retry-After / 403 / 429 / 5xx handling
- `parse_edgar_submissions`
- `CikSecurityMapping`
- `acquire_company_corpus`
- immutable raw landing zone under
  `var/research-data/raw/sec-edgar/<acquisition_id>/`
- `acquisition.json`, `documents.jsonl`, and immutable raw filing payloads
- resume/idempotent re-run behavior
- per-filing `metadata.json` and `submission.json`
- `SEC_AVAILABILITY_POLICY_V1`
- amendment/revision handling for `10-K/A`, `10-Q/A`, `8-K/A`
- `ACQUIRED_NOT_FULLY_MAPPED` Stage 1 state

The acquisition runner is:

`scripts/run_sec_edgar_acquisition.py`

Without `SEC_USER_AGENT`, it exits with:

```text
SEC_USER_AGENT_REQUIRED
```

It never sends a request without a declared compliant User-Agent.

## 4. CIK / Security Mapping

The runner requires a CIK mapping manifest with `source_identity` from a
certified market research dataset. A current CIK/ticker snapshot is rejected.

Template:

`config/research/cik_manifest.example.json`

## 5. Source Contract

`config/research/sec_edgar_source_contract.json` declares:

- source kind: `SEC_FILING`
- availability timestamp proven: `true`
- revision history: `true`
- symbol mapping: `true`
- timezone: `true`
- immutable raw payload: `true`
- rate-limit compliant: `true`

## 6. PIT Certification

Corpus certification remains `NOT_CERTIFIABLE` until a real corpus is acquired
and passes:

- future document exclusion
- future revision exclusion
- revision chronology
- availability timestamp
- timezone
- symbol mapping
- raw checksum
- duplicate detection
- replay safety

## 7. Exact Remaining Blockers

1. User must set `SEC_USER_AGENT` to a declared contact, e.g.
   `Company Name admin@example.com`.
2. User must provide a certified CIK-to-`permanent_security_id` mapping manifest
   with `source_identity` bound to the certified market research dataset.
3. Run `scripts/run_sec_edgar_acquisition.py` for the target CIK range.
4. Run `scripts/run_text_corpus_certification.py` on the immutable corpus.
5. Only then can DeepSeek historical extraction be run on certified text.

Stage 1 raw acquisition may run before the mapping manifest exists by using:

```text
--allow-unmapped
```

The resulting corpus is:

`ACQUIRED_NOT_FULLY_MAPPED`

It is not eligible for formal LLM Alpha research until mapping is complete.
