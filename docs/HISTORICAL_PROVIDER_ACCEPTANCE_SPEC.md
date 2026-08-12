# Historical Provider Acceptance Spec

Date: 2026-08-12

## 1. Purpose

This spec defines how a historical US equity research provider is accepted into
the Personal Alpha Terminal research data foundation.

Acceptance does not mean the strategy is approved. It means the provider and the
normalized package satisfy the survivorship-safe, PIT-safe research data
contract.

## 2. Provider Contract

A provider contract is a JSON object accepted by `ProviderContract`.

Required fields:

```json
{
  "provider_id": "norgate-or-crsp",
  "provider_version": "2026-08-01",
  "provider_security_id_scheme": "provider-permanent-id",
  "permanent_identifiers": true,
  "delisting_history": true,
  "delisting_returns": true,
  "historical_membership": true,
  "corporate_actions_pit": true,
  "total_return_pit": true,
  "benchmark_same_pit": true,
  "license_scope": "PERSONAL_LOCAL_RESEARCH",
  "local_research_use_allowed": true,
  "derived_research_allowed": true,
  "schema_mapping_version": "norgate-to-research-v1",
  "source_identity": "signed-provider-manifest-id",
  "known_limitations": []
}
```

`known_limitations` is optional.

## 3. Acceptance Rules

The package must pass `certify_research_package` first.

Provider acceptance additionally requires:

- `use_scope` must be `PRODUCTION_RESEARCH`.
- package `provider` must equal contract `provider_id`.
- license must permit local storage and derived research.
- if `permanent_identifiers` is true, every security must have at least one of
  `provider_security_id`, `cusip`, or `figi`.
- if `delisting_history` is true, delisted securities must have lifecycle
  actions.
- if `delisting_returns` is true, terminal actions must have `terminal_return`.
- if `historical_membership` is true, package must contain membership rows.
- if `corporate_actions_pit` is true, package must contain corporate actions.
- if `total_return_pit` is true, package must pass PIT total-return
  certification.
- if `benchmark_same_pit` is true, package must contain SPY and QQQ benchmark
  securities and matching PIT price coverage.

## 4. Statuses

`PASS`:

- no acceptance blockers
- no known provider limitations

`PASS_WITH_LIMITATIONS`:

- no acceptance blockers
- provider declares known limitations, or no delisted case was observed while
  delisting history is claimed

`NOT_CERTIFIABLE`:

- any acceptance blocker
- any row certification blocker
- `TEST_FIXTURE` package

## 5. Dataset Manifest

Every accepted package produces:

- `ResearchDatasetManifestV2`
- immutable row payload
- `content_hash`
- `coverage_hash`
- `corporate_action_identity`
- provider and acquisition identity
- certification state

The acceptance runner persists both:

- provider acceptance JSON
- normalized research dataset under `var/research-data/acceptance/datasets`

## 6. Command

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

CSV, Parquet, and SQLite import are supported.

Before acceptance, `verify_raw_landing_zone` checks:

- raw manifest identity
- immutable file checksums and sizes
- license scope
- provider/version identity

Exit code is non-zero for `NOT_CERTIFIABLE`.

## 7. Prohibited Inputs

- current Nasdaq/NYSE constituent lists used as historical membership
- final adjusted price history presented as PIT total-return vintage
- delisted securities dropped without terminal lifecycle
- missing delisting returns or terminal prices assumed to be zero
- fixtures, web scrapes, or LLM knowledge used as production research evidence
- any license that does not permit local research storage or derived research

## 8. Current State

No real provider contract or research package is installed. The acceptance
infrastructure is implemented and tested, but the workspace remains
`NOT_CERTIFIABLE` until a licensed or user-supplied survivorship-safe package is
provided and accepted.
