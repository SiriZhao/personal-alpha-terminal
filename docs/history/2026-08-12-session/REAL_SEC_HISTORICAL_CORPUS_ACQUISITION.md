# Real SEC Historical Corpus Acquisition

Date: 2026-08-12

Status: **PASS for a bounded real pilot; permanent security mapping pending**

## 1. Official SEC Policy Verified

Verified from the current SEC pages:

- Fair access max request rate: 10 requests/second.
- SEC asks users to download only what they need and to moderate load.
- Declared bot User-Agent is required in request headers.
- EDGAR data APIs on `data.sec.gov` and archive documents on `www.sec.gov`
  are the acquisition targets.

Project behavior:

- `SEC_USER_AGENT_PRESENT=true`
- Project limiter: 1 request/second, below the official 10 req/s ceiling.
- No full User-Agent is written to logs or reports.

The live response also showed that current `submissions` JSON uses a
column-oriented `filings.recent` object. The existing parser now supports both
the row-oriented and current column-oriented official shapes.

## 2. Stage A Connectivity Smoke Test

Result: `PASS`

- Endpoint: `https://data.sec.gov/submissions/`
- HTTP class: 200
- Response parsed: true
- Rate limiter active: true
- Local archive writable: true
- `SEC_USER_AGENT_PRESENT=true`

The smoke test exposed and fixed two real network compatibility issues:

- SEC returned gzip-compressed payloads; the client now decodes `gzip` and
  `deflate`.
- Current submissions `recent` is columnar; the parser now accepts that shape.

## 3. Real Pilot

Acquisition ID: `real-pilot-tesla-2025-h1`

CIK: `1318605` (Tesla, Inc.)

Coverage:

- start: `2025-01-02`
- end: `2025-04-30`

Forms:

- `10-K`: 1
- `10-K/A`: 1
- `10-Q`: 1
- `8-K`: 4

Total real documents: `7`

Issuers: `1`

Acquisition state:

`ACQUIRED_NOT_FULLY_MAPPED`

## 4. Immutable Raw Landing Zone

Landing zone:

`var/research-data/text-corpus/raw/sec/real-pilot-tesla-2025-h1/`

Each filing contains:

- `raw.txt`
- `metadata.json`
- `submission.json`

Verification passed:

- raw payload checksum: PASS
- normalized checksum: PASS
- acceptance timestamps: 7/7 complete
- timezone metadata: 7/7 complete
- duplicate redownload identity: PASS
- corruption detection: PASS

Acquisition raw content hash:

`c69ae367583cffd5106419f745038a4772fc9069ff3b42ad5929e5a1206f64b8`

## 5. Amendment

A real `10-K/A` was present and linked to the real original `10-K`.

- original document identity: `sec-1318605-000162828025003063`
- amendment raw identity: `sec-1318605-000110465925042659`
- amendment `document_id` is bound to the original
- `revision_id` is `amendment-000110465925042659`

## 6. Real SEC Evidence

- 7 real SEC filings downloaded from official SEC endpoints.
- Official SEC accession, CIK, form, filing date, report date, and acceptance
  timestamp were used.
- Local `retrieval_timestamp` is separate from historical `available_at`.
- Immutable raw files and checksums were verified on the local landing zone.

## 7. Fixture / Test Evidence

- Unit tests use synthetic `BytesIO` responses and synthetic submissions JSON.
- Fixture evidence is explicitly labelled as tests and is never used as real
  acquisition evidence.
- Real evidence in this report is limited to the bounded pilot above.

## 8. Status

`SEC_SOURCE_ACQUISITION = PASS`

`SECURITY_MAPPING = PENDING`

No current-ticker list is treated as a survivorship-safe historical universe.
