# Real Market Data Acquisition Report

Date: 2026-08-12

Result: **BLOCKED_EXTERNAL_DATA**

This report covers historical US equity market research data only. The ROUND
2.5B real SEC corpus is a separate text-corpus acquisition and is not treated
as market research data.

## 1. Acquisition Attempt

The environment was checked for existing market-data credentials and licensed
packages. The following are all absent:

- `TWELVE_DATA_API_KEY`
- `ALPHA_VANTAGE_API_KEY`
- `FMP_API_KEY`
- `POLYGON_API_KEY`
- `TIINGO_API_KEY`
- `ALPACA_API_KEY`
- `SHARADAR_API_KEY`
- `NASDAQ_DATALINK_API_KEY`
- `NORGATE_PACKAGE_PATH`
- `EODHD_API_KEY`
- `FINNHUB_API_KEY`
- `MARKETSTACK_API_KEY`
- `XIGNITE_API_KEY`
- `DATABENTO_API_KEY`
- `INTRINIO_API_KEY`

No package was found under `var/research-data/raw/`.

No purchase, subscription, billing action, or license acceptance was
performed. This report does not expose secret values.

## 2. Current Real Layers

Latest local evidence is in:

`artifacts/latest/historical_data_acquisition.json`

Observed real local layers:

- live price rows: `9073`
- live security count: `18`
- current directory securities: `8833`
- current directory common equities: `5263`
- historical security master rows: `0`
- historical membership rows: `0`
- delisted count: `0`
- unknown lifecycle count: `8833`
- corporate action rows: `3`
- PIT total-return rows: `234`
- actual price coverage: `2024-08-07` to `2026-08-11`
- calendar coverage: `2015-01-02` to `2026-08-11`
- research dataset content hash: not generated
- classification: `NOT_CERTIFIABLE`
- OOS lock status: `NOT_CREATED_RESEARCH_DATA_NOT_CERTIFIED`

The local benchmark rows (`SPY=504`, `QQQ=504`) are inventory-only live rows and
are not PIT total-return research evidence.

## 3. Raw Landing Zone

The existing implementation provides:

- `var/research-data/raw/<provider_id>/<acquisition_id>/`
- immutable `manifest.json`
- SHA-256 and size verification per raw file
- `RawAcquisitionManifest`
- `verify_raw_landing_zone`
- `LocalResearchPackageAdapter`
- resume/checkpoint support through `AcquisitionCheckpoint`

No licensed market-data raw landing zone was created because no licensed
package exists.

## 4. Acceptance

The formal entry points exist:

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

Acceptance was not run on a real provider package because none is installed.
Running it on a synthetic fixture would not satisfy the real-data requirement.

## 5. Coverage

Frozen research requirement:

- 252 warmup
- 1008 train
- 504 validation
- 21 embargo
- 252 locked OOS
- 2037 total sessions
- required start `2018-07-03`
- required end `2026-08-11`

Current real local price coverage starts `2024-08-07` and is not certified
research data. The required `2037`-session research universe is not satisfied.

## 6. Blockers

1. No licensed market-data package or credential is installed.
2. No permanent security master.
3. No ticker history.
4. No listing/delisting lifecycle.
5. No delisting return or terminal price.
6. No historical membership.
7. No PIT corporate actions.
8. No PIT total-return vintages.
9. No same-convention SPY/QQQ research benchmark.
10. Required coverage from `2018-07-03` is not available in a certified
    research package.

## 7. Real vs Fixture/Test Evidence

**Real evidence:** absence of credentials/package, live-only local inventory,
official provider documentation, and raw-landing-zone/acceptance implementation.

**Fixture/test evidence:** deterministic unit tests for provider mapping,
permanent ID stability, ticker changes, listing/delisting, terminal returns,
future membership leakage, corporate-action PIT, total-return vintage,
benchmark identity, duplicate rows, provider version, resume, corrupted raw
payload, content hash, and license rejection.

Fixture tests do not create a certified dataset.

## 8. User Action Required

To continue without lowering standards, the user must supply one of:

- a licensed CRSP package with documented delisting/PIT conventions
- a licensed Norgate Platinum package plus explicit EULA confirmation for local
  derived research
- another provider package that can satisfy every `ProviderContract` field

Status:

`ROUND_3_MARKET_DATA_DEPENDENCY = BLOCKED`
