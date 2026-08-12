# SEC PIT Availability Certification

Date: 2026-08-12

Policy version: `SEC_AVAILABILITY_POLICY_V1`

Result: **PASS for real bounded pilot source certification; mapping pending**

## 1. Historical Availability Semantics

Historical availability is based on SEC official acceptance metadata:

- `acceptanceDateTime` from official SEC submissions JSON is the primary
  historical availability evidence.
- Local download time is recorded separately as `retrieval_timestamp` and
  `ingested_at`.
- Local download time is never used as historical `available_at`.
- Filing date, report period end, and current webpage display time are not
  used as historical availability.
- A filing without a valid acceptance timestamp cannot be PIT-certified.

## 2. Real Pilot Certification

Pilot: `real-pilot-tesla-2025-h1`

CIK: `1318605`

Documents: `7`

Acceptance timestamp completeness: `7/7`

Timezone completeness: `7/7`

Coverage:

- start: `2025-01-02`
- end: `2025-04-30`

All `available_at` values come from SEC acceptance metadata, not local
retrieval.

## 3. Raw Content Hash

Per-filing raw checksum: PASS

Normalized checksum: PASS

Corpus `raw_content_hash`:

`4e4489094e3249cff89d40ac34f8aeb733e219de9ec44ae33b907b79035e26a3`

Repeated download of the same filing does not create a different logical
identity. Existing raw files are never overwritten with changed content.

## 4. Amendment / Revision Semantics

The real `10-K/A` is linked to the original `10-K`.

Before the amendment `available_at`, replay sees the original filing.

After the amendment `available_at`, replay sees both the original and the
amendment revision.

A later amendment never changes an earlier replay hash.

## 5. Real SEC Evidence

- Official SEC acceptance timestamps are present for every pilot filing.
- Raw and normalized checksums are verified against the immutable landing
  zone.
- The real amendment is bound to its real original filing.
- Local retrieval timestamps are not used as historical availability.

## 6. Fixture / Test Evidence

- Fixture tests validate the same policy with synthetic records.
- Fixture tests do not count as real availability certification.
- Real availability certification is limited to the 7 real filings above.

## 7. State

`PIT_SOURCE_CERTIFICATION = PASS`

`SECURITY_MAPPING = PENDING`

The corpus remains `SECURITY_MAPPING_PENDING`, not `PIT_TEXT_CERTIFIED`,
because permanent security mapping is not yet available.
