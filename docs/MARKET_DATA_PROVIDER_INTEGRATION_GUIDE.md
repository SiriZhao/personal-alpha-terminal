# Market Data Provider Integration Guide

Date: 2026-08-12

This guide describes how to install, normalize, and certify a licensed US
historical market-data package in Personal Alpha Terminal.

## 1. Credential Configuration

Credentials must be supplied through environment variables or an existing
secure config. Never write secret values into source, docs, logs, fixtures, or
git.

Expected environment variables:

- `TWELVE_DATA_API_KEY`
- `ALPHA_VANTAGE_API_KEY`
- `POLYGON_API_KEY`
- `TIINGO_API_KEY`
- `ALPACA_API_KEY`
- `SHARADAR_API_KEY`
- `NASDAQ_DATALINK_API_KEY`
- `EODHD_API_KEY`
- `FINNHUB_API_KEY`
- `MARKETSTACK_API_KEY`
- `XIGNITE_API_KEY`
- `DATABENTO_API_KEY`
- `INTRINIO_API_KEY`

For local package delivery, the expected variables are:

- `NORGATE_PACKAGE_PATH`
- `CRSP_PACKAGE_PATH`

As of `2026-08-12`, none of these market-data variables is set in this
environment. The presence check should report only `SET` / `NOT_SET`, never the
value.

## 2. Package Placement

Place a licensed raw package under:

```text
var/research-data/raw/<provider_id>/<acquisition_id>/
```

Expected layout:

```text
var/research-data/raw/norgate_data/acq-001/
  manifest.json
  provider-export/
    prices.csv
    securities.csv
    ...
```

Raw files must not be modified after landing.

## 3. Normalization

Vendor conversion should produce a long-form CSV, Parquet, or SQLite package
accepted by:

```python
from personal_alpha_terminal.quant_engine.research_dataset import import_research_package
```

Required row families:

- `SECURITY`
- `MEMBERSHIP`
- `PRICE`
- `CORPORATE_ACTION`
- `CALENDAR`

PIT timestamps must be timezone-aware. Current final adjusted prices must not
be marked as PIT total-return vintages.

## 4. Raw Manifest

Create the raw manifest with:

```python
from datetime import UTC, datetime

from personal_alpha_terminal.quant_engine.research_provider_adapters import (
    RawFileEntry,
    build_raw_manifest,
    persist_raw_manifest,
)

manifest = build_raw_manifest(
    provider_id="norgate_data",
    provider_version="2026-08-01",
    acquisition_id="acq-001",
    source_identity="provider-manifest-id",
    retrieved_at=datetime.now(UTC),
    license_scope="PERSONAL_LOCAL_RESEARCH",
    local_research_use_allowed=True,
    derived_research_allowed=True,
    files=(
        RawFileEntry(
            path="provider-export/prices.csv",
            sha256="...",
            size_bytes=12345,
            role="raw",
        ),
    ),
    coverage_start=date(2018, 7, 3),
    coverage_end=date(2026, 8, 11),
)
persist_raw_manifest(manifest, root)
```

`manifest.json` is immutable. A changed source payload must create a new
acquisition ID and new raw landing zone.

## 5. Provider Contract

Create a `ProviderContract` JSON from the licensed package and signed license.
Unknown capabilities must be blockers.

Required contract fields:

- permanent identifiers
- delisting history and returns
- historical membership
- PIT corporate actions
- PIT total-return vintages
- same-convention SPY/QQQ benchmark
- local storage and derived-research permission

## 6. Acceptance

Run:

```text
python scripts/run_market_data_provider_acceptance.py \
  path/to/normalized-research.csv \
  --contract path/to/provider-contract.json \
  --provider-version provider-version \
  --raw-root var/research-data/raw/<provider_id>/<acquisition_id> \
  --required-start 2018-07-03 \
  --required-end 2026-08-11 \
  --output var/research-data/acceptance
```

Acceptance writes:

- provider acceptance JSON
- normalized research dataset
- `ResearchDatasetManifestV2`
- `content_hash`
- `coverage_hash`
- `corporate_action_identity`

If the package is a `TEST_FIXTURE`, acceptance fails with
`TEST_FIXTURE_IS_NOT_PRODUCTION_RESEARCH`.

## 7. Refresh

Refresh must:

1. create a new acquisition ID;
2. create a new immutable raw landing zone;
3. preserve all prior raw acquisitions;
4. rerun normalization with a deterministic schema version;
5. rerun acceptance with the same or documented new provider version;
6. publish a new manifest/content hash.

Do not overwrite an earlier acquisition.

## 8. Troubleshooting

- `PROVIDER_ID_MISMATCH`: package `provider` differs from contract.
- `RAW_FILE_CHECKSUM_MISMATCH`: raw payload changed after landing.
- `DELISTED_LIFECYCLE_INCOMPLETE`: delisted securities lack terminal actions.
- `CURRENT_CONSTITUENT_HISTORY_NOT_ALLOWED`: current snapshots cannot be used
  as historical membership.
- `TOTAL_RETURN_PIT_EVIDENCE_INCOMPLETE`: adjusted current series cannot be
  used as PIT total-return vintages.
- `CORPORATE_ACTION_PIT_EVIDENCE_MISSING`: no PIT action availability was
  supplied.
- `BENCHMARK_PIT_NOT_CLAIMED`: provider contract does not prove SPY/QQQ
  same-PIT compatibility.

## 9. Do Not Do

- Do not join by ticker alone.
- Do not backfill a current ticker universe into the past.
- Do not treat current final adjusted prices as PIT total-return vintages.
- Do not set missing terminal returns to zero.
- Do not run acceptance on a fixture and call it real evidence.
