# Real Historical Text Corpus Final

Date: 2026-08-12

Result: **non-empty real corpus; certification state SECURITY_MAPPING_PENDING**

## 1. Corpus Manifest

Manifest path:

`artifacts/latest/sec-edgar-corpus/1b8fe9e3b99eeaafb1e097f4d34a06633ef1897a353b6e06abd843bf255e9e00.json`

Fields:

- corpus ID: `sec-edgar-real-pilot-tesla-2025-h1`
- documents: `7`
- issuers: `1`
- `10-K`: `1`
- `10-Q`: `1`
- `8-K`: `4`
- amendments: `1`
- revisions: `2`
- duplicates: `0`
- mapped securities: `0`
- unmapped issuers: `1`
- coverage start: `2025-01-02`
- coverage end: `2025-04-30`
- availability complete: `true`
- extraction coverage: `1/7`
- certification state: `SECURITY_MAPPING_PENDING`
- raw content hash: `4e4489094e3249cff89d40ac34f8aeb733e219de9ec44ae33b907b79035e26a3`
- manifest hash: `1b8fe9e3b99eeaafb1e097f4d34a06633ef1897a353b6e06abd843bf255e9e00`

## 2. Blockers

- `SYMBOL_MAPPING_INCOMPLETE`

No non-mapping blocker remains for this pilot.

## 3. Mapping Status

Mapping is pending:

`LLM_RESEARCH_DATA_DEPENDENCY = SECURITY_MAPPING_PENDING`

No permanent security ID was invented. Stage-1 identity is complete and stable:

`CIK + accession`

Future mapping can add:

- CIK
- company
- permanent security ID
- ticker as of

## 4. DeepSeek Extraction

One real SEC `8-K` was processed through the existing DeepSeek pipeline.

Structured event status: `READY`

Event type: `EARNINGS`

Event `data_cutoff` is the SEC historical acceptance time, not local retrieval
time.

## 5. Historical Replay

Replay was run on the real corpus at four historical cutoffs.

Checks passed:

- future filing invisible
- future amendment invisible
- original and amendment versions correct
- earlier replay hash unchanged by future filings
- repeated replay deterministic

Replay production readiness remains `NOT_CERTIFIABLE` because market data and
permanent security mapping are not certified.

## 6. Real SEC Evidence

- 7 real SEC filings
- non-empty raw content hash
- verified immutable raw landing zone
- real acceptance timestamps
- real amendment semantics
- real DeepSeek extraction event
- real multi-cutoff replay

## 7. Fixture / Test Evidence

- Existing and newly added unit tests use fixtures and synthetic network
  responses.
- Fixture metrics are not included in the real corpus counts above.

## 8. Overall Status

`SEC_SOURCE_ACQUISITION = PASS`

`PIT_SOURCE_CERTIFICATION = PASS`

`SECURITY_MAPPING = PENDING`

`REAL_DEEPSEEK_EXTRACTION = PASS`

`REAL_HISTORICAL_REPLAY = PASS`

`FULL_RESEARCH_CORPUS = NOT_CERTIFIABLE`
