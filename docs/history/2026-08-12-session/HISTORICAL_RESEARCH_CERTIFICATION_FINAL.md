# Historical Research Certification Final

Date: 2026-08-12

Result: **NOT_CERTIFIABLE**

This document records the current reproducible evidence. It does not claim that
live daily data, test fixtures, or provider capability pages are historical
research certification.

## 1. Market Dataset

The only row-level market evidence is live daily OHLCV in `var/personal_alpha.db`.
The latest refreshed daily run produced:

- Run: `daily-5b9f4d3812f14b329429fc2e79fc8796`
- Analysis date: `2026-08-11`
- Snapshot: `US-20260812T041448Z-fca2e8ce398f`
- Data hash: `fca2e8ce398f67fe95ff9562b2ff1de01ede6ce4fdecb1ee57a8ac1fe29ab8ba`
- PIT cutoff: `2026-08-11T20:30:00+00:00`
- Raw price rows: `9073`
- Live securities: `18`
- Benchmark rows: SPY `504`, QQQ `504`
- Corporate actions: `3`
- PIT total-return versions: `234`

This is `LIVE_DAILY_DATA`, not a `RESEARCH_CERTIFIED_DATA` package.

## 2. Historical Research Layers

Latest acquisition manifest:

- Acquisition ID: `historical-acquisition-f186c8c477aff91b6f25`
- Manifest hash: `f186c8c477aff91b6f253a2c43c57a9d29cd8983140a0df2e8bba2fb65e1ce9b`
- Research baseline: `historical-research-baseline-083e7004b2cfcc4bf4f6`
- Historical security master: `0`
- Historical membership rows: `0`
- Membership coverage: `0.0%`
- Delisted securities: `0`
- Security identifier history: `0`
- PIT corporate-action history: none
- PIT total-return history: none
- `research_dataset_content_hash`: `null`
- Classification: `NOT_CERTIFIABLE`
- Production eligible: `false`

The current Nasdaq Trader directory contains `8833` securities, of which `5263`
are conservatively classified as common-equity records. It is a current listing
snapshot only and cannot backfill historical membership.

## 3. Survivorship and Point-in-Time State

Survivorship status: `UNVERIFIED`.

`SURVIVORSHIP_SAFE = FALSE`.

The project rejects the use of current constituents as historical membership.
There is no available way to reconstruct:

- entry/exit membership histories by universe and session;
- delisted securities and terminal returns;
- ticker/identifier vintages and symbol changes;
- PIT corporate-action availability;
- PIT total-return vintages;
- same-PIT benchmark histories.

## 4. Historical Text / Event Corpus

Historical text/event state: **NOT_CERTIFIABLE**.

Real corpus evidence:

- `intelligence_raw_information`: `0`
- `intelligence_events`: `0`
- `intelligence_event_evidence`: `0`
- `intelligence_extraction_cache`: `0`
- No certified SEC filing, earnings release, transcript, announcement, news, or
  event-feed historical package exists in the workspace.

Software invariants for `RawInformation`, `UnifiedEvent`, `HistoricalAIReplay`,
availability cutoffs, source hashes, deduplication, and revision visibility pass
automated tests. Those invariants are not corpus certification.

For every future source, certification must establish:

- original source and source timestamp;
- provider-received and availability timestamps;
- immutable raw payload/checksum;
- symbol mapping and timezone;
- duplicate and restatement handling;
- replay safety at every historical cutoff.

No fixture or current-web scrape may be used as historical availability.

## 5. Dataset Identity

The current acquisition has a stable inventory hash and manifest hash, but no
row-level research dataset hash because no research rows exist.

- Inventory hash: `9946445a484e2552de28a473718315dc5ff3f0c14ee9d549b3d0427bce233fd8`
- Research dataset content hash: `null`

Research results must bind to a unique dataset identity before Alpha, OOS, or
Champion/Challenger evidence is reported.

## 6. Remaining Blocking Evidence

1. `HISTORICAL_MEMBERSHIP_INCOMPLETE`
2. `CURRENT_CONSTITUENT_HISTORY_NOT_ALLOWED`
3. `DELISTING_HISTORY_INCOMPLETE`
4. `SECURITY_IDENTIFIER_HISTORY_INCOMPLETE`
5. `DELISTING_RETURN_UNAVAILABLE`
6. `CORPORATE_ACTION_PIT_HISTORY_INCOMPLETE`
7. `PIT_TOTAL_RETURN_HISTORY_INCOMPLETE`
8. `REQUIRED_PERIOD_COVERAGE_INCOMPLETE`
9. `BENCHMARK_PIT_TOTAL_RETURN_CONVENTION_INCOMPLETE`
10. No certified historical text/event corpus.

The minimum research period remains:

- 252 factor warmup sessions
- 1008 TRAIN sessions
- 504 VALIDATION sessions
- 21 EMBARGO sessions
- 252 locked-OOS sessions
- total 2037 sessions
- required end `2026-08-11`
- required minimum start `2018-07-03`

Current real price coverage is `2024-08-07` through `2026-08-11`, so it is far
below the research requirement even before survivorship blockers are addressed.

## 7. Round 2.5A/B Update

Round 2.5A completed official provider selection and a provider-neutral raw
landing zone/adapter, but no licensed package was available:

- market data: `BLOCKED_EXTERNAL_DATA`
- recommended provider: Norgate US Stocks Platinum, trial-first
- fallback provider: CRSP US Stock Databases
- provider matrix: `artifacts/latest/provider_selection_matrix.json`

Round 2.5B completed the official SEC EDGAR acquisition implementation and
empty-corpus certification:

- SEC acquisition: `SEC_USER_AGENT_REQUIRED`
- real SEC documents: `0`
- corpus certification: `NOT_CERTIFIABLE`
- DeepSeek historical replay: `NOT_RUN`
- LLM feature production status: `SHADOW`
