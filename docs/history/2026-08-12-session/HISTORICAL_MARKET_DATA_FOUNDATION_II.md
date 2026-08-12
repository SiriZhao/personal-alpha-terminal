# Historical Market Data Foundation II

Date: 2026-08-12

Result: **NOT_CERTIFIABLE**

This round completed the provider-neutral research data foundation. It did not
attempt to certify Yahoo, Nasdaq Trader, or any other survivorship-biased live
source as historical research data.

## 1. Research Data Contract

The normalized contract now supports:

- Security master:
  - `permanent_security_id`
  - `ticker`
  - `ticker_valid_from`
  - `ticker_valid_to`
  - `exchange`
  - `security_type`
  - `listing_date`
  - `delisting_date`
  - `delisting_reason`
  - optional `cusip`
  - optional `figi`
  - optional `provider_security_id`
  - optional `company_id`
  - optional `company_name`
- Historical universe membership:
  - `universe_id`
  - `universe_type`
  - `effective_from`
  - `effective_to`
  - `available_at`
  - `source_timestamp`
  - `membership_source_type`
- Prices:
  - `open`, `high`, `low`, `close`, `volume`
  - `adjustment_kind` with `RAW`, `PIT_TOTAL_RETURN_VINTAGE`, or
    `CURRENT_FINAL_ADJUSTED`
  - PIT total-return value, availability, and vintage ID
- Corporate actions:
  - `SPLIT`
  - `CASH_DIVIDEND`
  - `STOCK_DIVIDEND`
  - `MERGER`
  - `SPIN_OFF`
  - `SYMBOL_CHANGE`
  - `DELISTING`
  - `effective_date`, `announcement_date`, `available_at`
  - `revision_id`, `terminal_return`, `terminal_price`
- Delisting:
  - `terminal_return` required for delisted securities
  - `terminal_price` required for delisted securities
- Benchmarks:
  - SPY and QQQ are represented as `BENCHMARK` securities
  - benchmark membership and prices are part of the same PIT package

## 2. Dataset Manifest

`ResearchDatasetManifestV2` now includes:

- `provider`
- `provider_version`
- `acquisition_id`
- `schema_version`
- `retrieved_at`
- `date_start`
- `date_end`
- `security_count`
- `active_security_count`
- `delisted_count`
- `universe_count`
- `membership_count`
- `corporate_action_count`
- `calendar_session_count`
- `benchmark_universe_id`
- `corporate_action_identity`
- `content_hash`
- `coverage_hash`
- `inventory_hash`
- `license_scope`
- `known_limitations`
- `certification_state`
- `blockers`
- `manifest_hash`

Research results must bind to `content_hash`.

## 3. Provider Acceptance Audit

New module:

`src/personal_alpha_terminal/quant_engine/research_provider_acceptance.py`

It provides:

- `ProviderContract`
- `HistoricalResearchDataProvider` protocol
- `accept_research_provider`
- `persist_provider_acceptance`

Acceptance statuses:

- `PASS`
- `PASS_WITH_LIMITATIONS`
- `NOT_CERTIFIABLE`

Acceptance requires:

- production research scope, not `TEST_FIXTURE`
- matching provider identity
- local research storage permission
- derived research permission
- permanent identifiers when claimed
- delisting history and returns when claimed
- historical membership when claimed
- PIT corporate actions when claimed
- PIT total returns when claimed
- same-PIT SPY/QQQ benchmark evidence when claimed

## 4. PIT and Survivorship Auditor

The row-level certification now fails closed on:

- current-snapshot backfill into history
- future membership leakage
- future corporate-action leakage
- future price rows
- future total-return revision leakage
- price rows before listing
- price rows after delisting
- ticker vintage mismatch
- missing delisting lifecycle
- missing delisting return
- missing delisting terminal price
- current adjusted series used as PIT total return
- duplicate provider rows
- calendar mismatch
- incomplete required research coverage

## 5. Current Real Data State

No licensed or user-supplied research package is installed. The current
workspace remains:

- historical security master: `0`
- historical membership: `0`
- delisted securities: `0`
- identifier history: `0`
- research dataset content hash: `null`
- `SURVIVORSHIP_SAFE = FALSE`
- benchmark same-PIT history: unavailable
- full required research coverage: unavailable

The frozen research requirement remains:

- 252 warmup
- 1008 TRAIN
- 504 VALIDATION
- 21 EMBARGO
- 252 locked OOS
- 2037 total sessions

## 6. Runnable Acceptance Pipeline

Run:

```text
python scripts/run_market_data_provider_acceptance.py \
  path/to/research.csv \
  --contract path/to/provider-contract.json \
  --provider-version provider-version \
  --raw-root var/research-data/raw/<provider>/<acquisition_id> \
  --required-start 2018-07-03 \
  --required-end 2026-08-11 \
  --output var/research-data/acceptance
```

The script writes an immutable acceptance JSON and the normalized research
dataset manifest. It exits non-zero when the provider is `NOT_CERTIFIABLE`.

The raw landing zone is verified before acceptance, including SHA-256 checksums,
provider version, license scope, and immutable source identity.

## 7. Verification

- Ruff: `PASS`
- strict mypy: `PASS`
- pytest: `695 passed`
- secret scan: `SECRET_SCAN_PASS`
- provider adapter and raw-landing tests: `PASS`
- empty real SEC corpus runner: `NOT_CERTIFIABLE`

## 7b. Round 2.5A Status

Provider selection evidence is exported to:

`artifacts/latest/provider_selection_matrix.json`

No real licensed market-data package is installed. The round is therefore:

`BLOCKED_EXTERNAL_DATA`

## 8. Blocking Evidence

1. No licensed or supplied survivorship-safe US historical research package.
2. No permanent security identity archive with CUSIP/FIGI/provider ID history.
3. No delisting/terminal-return archive.
4. No historical universe membership timeline.
5. No PIT corporate-action and total-return vintages.
6. No same-PIT SPY/QQQ benchmark history.
7. No 2037-session research panel.

The infrastructure is ready. Certification remains blocked by real data, not by
a missing contract, acceptance audit, manifest, or fail-closed validation path.
