# SEC EDGAR Integration Guide

Date: 2026-08-12

## 1. User-Agent

Set a declared contact before running any SEC request:

```powershell
$env:SEC_USER_AGENT = "Company Name admin@example.com"
```

Do not put a fake name or email into the repository. The value is read from the
environment and is never written to logs, docs, fixtures, or git.

## 2. CIK Mapping

Create `var/research-data/cik-mapping.json` using:

`config/research/cik_manifest.example.json`

Set `source_identity` to the certified market research dataset content hash.
Do not use a current ticker snapshot as historical CIK mapping.

## 3. Acquisition

```text
python scripts/run_sec_edgar_acquisition.py \
  --cik 320193 \
  --mapping path/to/cik-mapping.json \
  --source config/research/sec_edgar_source_contract.json \
  --acquisition-id sec-edgar-2026-08-11 \
  --provider-version sec-edgar-v1 \
  --required-start 2018-07-03 \
  --required-end 2026-08-11 \
  --cutoff 2026-08-11T20:30:00+00:00 \
  --max-documents 1000 \
  --rate-limit 1.0 \
  --output var/research-data/raw/sec-edgar \
  --corpus-output var/research-data/text-corpus
```

The command will not fetch unless `SEC_USER_AGENT` is present.

## 4. Raw Landing Zone

Acquired files:

```text
var/research-data/text-corpus/raw/sec/<acquisition_id>/
  acquisition.json
  documents.jsonl
  <CIK>/<accession-no-dashes>/
    raw.txt
    metadata.json
    submission.json
```

Raw payloads are immutable. Re-running the same acquisition is idempotent.

## 4b. Stage 1 Without Security Mapping

Run raw acquisition before ROUND 2.5A mapping is ready:

```text
python scripts/run_sec_edgar_acquisition.py \
  --cik 320193 \
  --source config/research/sec_edgar_source_contract.json \
  --allow-unmapped \
  --acquisition-id sec-edgar-stage1 \
  --required-start 2018-07-03 \
  --required-end 2026-08-11 \
  --cutoff 2026-08-11T20:30:00+00:00 \
  --output var/research-data/text-corpus/raw/sec \
  --corpus-output var/research-data/text-corpus
```

Stage 1 status:

`ACQUIRED_NOT_FULLY_MAPPED`

Stage 2 adds:

```text
--mapping path/to/cik-mapping.json
```

## 5. Certification

Run corpus certification after acquisition:

```text
python scripts/run_text_corpus_certification.py \
  --root var/research-data/raw/sec-edgar/<acquisition_id> \
  --source config/research/sec_edgar_source_contract.json \
  --corpus-id sec-edgar-<cik> \
  --cutoff 2026-08-11T20:30:00+00:00 \
  --required-start 2018-07-03 \
  --required-end 2026-08-11 \
  --provider-version sec-edgar-v1 \
  --output var/research-data/text-corpus
```

Only `PIT_TEXT_CERTIFIED` corpus is eligible for DeepSeek historical replay.

## 6. Troubleshooting

- `SEC_USER_AGENT_REQUIRED`: set `SEC_USER_AGENT`.
- `SEC_CIK_MAPPING_MISSING`: mapping file has no entry for the CIK.
- `SEC_ACCEPTANCE_TIMESTAMPS_MISSING`: SEC API did not provide an exact
  acceptance timestamp; corpus cannot certify that filing.
- `SEC_SECURITY_MAPPING_MISSING`: no certified permanent security mapping.
- `SEC_DOCUMENT_DOWNLOAD_FAILURES`: retry the acquisition; already-immutable raw
  files are preserved.
- `FUTURE_DOCUMENT_AT_CERTIFICATION_CUTOFF`: do not include filings after the
  historical cutoff.
