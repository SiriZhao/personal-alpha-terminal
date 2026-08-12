# ROUND 7 — HISTORICAL PIT DATA FOUNDATION & RESEARCH CERTIFICATION

Date: 2026-08-13
Branch: `codex/round7-historical-pit-foundation`
Baseline: ROUND 6 `LIVE PORTFOLIO LIFECYCLE: PASS` (commit `033cc07`, pushed)

## Executive Summary

ROUND 7 built the historical PIT data foundation: a unified provider
architecture, permanent identifiers, an immutable Raw Provider Snapshot ->
Certified PIT Dataset pipeline, a full certification framework with survivorship
classification, and research dataset versioning that invalidates old
certifications on any historical input change.  A gated research rerun executes
only on a certified dataset.

Because no licensed survivorship-safe historical source is currently installed
(the official capability audit shows CRSP requires a license and every free
provider lacks historical membership and/or delisting returns), the honest final
state is:

```text
HISTORICAL_PIT_LIMITED
```

No fake certification was produced; the framework is ready to certify a licensed
package when one is imported.

## 1. Provider Architecture

New package `src/personal_alpha_terminal/quant_engine/historical_pit/`:

- `HistoricalMarketDataProvider`  -> raw OHLCV, delisting returns, PIT TR vintages
- `SecurityMasterProvider`        -> permanent identifiers, symbol history,
                                     listing/delisting lifecycle
- `CorporateActionProvider`       -> PIT-aware corporate actions
- `HistoricalUniverseProvider`    -> historical membership, universe(as_of_date)
- `ResearchProviderCapabilities`  -> conservative evidence-backed capability claims
- `ProviderBundle` + `ResearchProviderRegistry` -> compose the four providers into
  a raw `ResearchDatasetPackage`; strategy code never imports a vendor adapter.

The registry refuses unknown or duplicate providers and composes a package in
the `RESEARCH_RAW_DATA` domain; certification is a separate gate.

## 2. Permanent Identifiers

`historical_pit/identifiers.py`:

- `InstrumentIdentity`: internal `instrument_id` + `provider_permanent_id` +
  ticker history vintages.
- `build_instrument_registry`: groups security vintages by the provider's
  permanent identity; a ticker change (e.g. TB -> TBN) keeps the SAME
  instrument; overlapping ticker vintages are a blocker.
- `resolve_ticker_on` / `symbol_history`: ticker-to-instrument resolution over
  time, proving a symbol change is never treated as a new company.

## 3. Delisting Retention

Delisted securities are preserved (listing/delisting dates, reason) and must
have a terminal lifecycle action (DELISTING/MERGER/ACQUISITION) with terminal
return and terminal price before certification.  Failed companies are never
deleted; `price_panel_from_package` retains delisted members.

## 4. Corporate Actions (PIT-aware)

`ResearchCorporateAction` distinguishes:
- economic effective date (`effective_date`)
- announcement date (`announcement_date`, must not follow effective)
- provider publication/vintage date (`available_at`, must not follow effective)

The framework rejects future leakage (`available_at.date() > effective_date`)
and symbol changes that create a new security id.

## 5. Total Return

`AdjustmentKind` explicitly separates:
- RAW
- PIT_TOTAL_RETURN_VINTAGE (certifiable)
- CURRENT_FINAL_ADJUSTED (never certifiable for history)

`price_panel_from_package` uses only RAW or PIT total-return vintage rows that
are available at the package cutoff; current-adjusted series are excluded.

## 6. Raw Data Immutability

`RawAcquisitionManifest` (existing) provides SHA-256 pinned raw files; the new
pipeline produces a `ResearchDatasetPackage` in `RESEARCH_RAW_DATA` which is
never overwritten downstream.  Certification produces a separate
`RESEARCH_CERTIFIED_DATA` manifest.

## 7. Certification Framework

`historical_pit/certification.py` combines:
- row certification (`certify_research_package`: schema, coverage, date range,
  identifiers, duplicates, future records, corporate-action integrity, delisted
  population, checksum, provider provenance)
- provider acceptance (`accept_research_provider`)
- survivorship classification (`classify_survivorship`)

`SurvivorshipClassification`:
- `SURVIVORSHIP_SAFE`    -> delisted retained, historical membership present,
                            delisting returns present, permanent ids + ticker
                            history, no current-snapshot backfill
- `SURVIVORSHIP_LIMITED` -> provider lacks delisting returns or historical
                            membership (or another blocker)
- `SURVIVORSHIP_UNVERIFIED` -> no security master evidence

`HistoricalPitVerdict`: `HISTORICAL_PIT_CERTIFIED` (every gate passes) or
`HISTORICAL_PIT_LIMITED` (any blocker).  No evidence is inferred or padded.

## 8. Research Dataset Versioning

`historical_pit/versioning.py`:

- `ResearchDatasetVersion` binds:
  - research_data_version
  - snapshot_hash
  - security_master_hash
  - corporate_action_hash
  - universe_hash
- `HistoricalDatasetVersionRegistry.publish` invalidates (supersedes) every
  older certification when a new version is published.
- `certification_is_current` is fail-closed: any historical input change makes
  an old certification non-current.

## 9. Research Rerun (gated)

`historical_pit/rerun.py`:

- `price_panel_from_package`: builds a ROUND 4-compatible price panel from a
  certified package (PIT-only, no future, no current-adjusted, delisted
  retained).
- `run_historical_research`: refuses to run when the verdict is
  `HISTORICAL_PIT_LIMITED` (blockers recorded, no fabricated rerun); when
  certified it runs factor IC, quantile return, walk-forward, probability
  calibration, and classical vs probability portfolio A/B, and reports a
  comparison structure against the ROUND 4 baseline.

## 10. CLI

New command `round7-research`:

- `status`   -> reports latest certified version or `HISTORICAL_PIT_LIMITED`,
                with the official provider capability audit.
- `certify`  -> certifies the latest imported research dataset (publishes a
                version only on CERTIFIED) using provider claim flags.
- `rerun`    -> gated historical research rerun; refuses on non-certified data.

## 11. Acceptance Evidence

`pat round7-research status` output:

```text
Latest certified version: NONE
Verdict: HISTORICAL_PIT_LIMITED
No licensed survivorship-safe historical dataset is installed. The free
current-directory providers cannot certify historical membership or delisting
returns, so certification is honestly withheld.
```

Official provider capability audit (abridged):

| Provider | Delisted | Perm ID | Ticker hist | Hist membership | Delist return | PIT vintages | Grade |
|---|---|---|---|---|---|---|---|
| nasdaq_trader | NO | NO | NO | NO | NO | NO | LIVE_ONLY |
| alpha_vantage | YES | NO | UNKNOWN | YES | NO | NO | RESEARCH_PARTIAL |
| twelve_data | UNKNOWN | PARTIAL | UNKNOWN | NO | NO | NO | RESEARCH_PARTIAL |
| tiingo | PARTIAL | PARTIAL | PARTIAL | NO | NO | NO | RESEARCH_PARTIAL |
| eodhd | YES | PARTIAL | UNKNOWN | NO | NO | NO | RESEARCH_PARTIAL |
| massinvestor | YES | PARTIAL | PARTIAL | YES | NO | NO | REQUIRES_LICENSE |
| norgate | PARTIAL | UNKNOWN | PARTIAL | PARTIAL | UNKNOWN | NO | CONDITIONAL |
| nasdaq_basic | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | NO | REQUIRES_LICENSE |
| crsp_historical | YES | YES | YES | YES | YES | PARTIAL | REQUIRES_LICENSE |

No current provider simultaneously claims historical membership + delisting
returns + PIT total-return vintages, so `HISTORICAL_PIT_LIMITED` is the
evidence-driven outcome.

## 12. Tests Added

`tests/unit/quant_engine/historical_pit/` (18 tests):
- `test_providers.py`      : four-provider composition, registry rejections,
                             capability fingerprint stability.
- `test_identifiers.py`    : ticker change keeps same instrument; symbol is not
                             a unique identity; deterministic registry.
- `test_versioning.py`     : five-hash bundle; any input change invalidates the
                             old certification; fail-closed without latest.
- `test_certification.py`  : survivorship-safe full package; missing delisting
                             returns / historical membership -> LIMITED;
                             current-snapshot backfill rejected; verdict gates.
- `test_rerun.py`          : LIMITED refuses to run; CERTIFIED executes the full
                             suite; price panel excludes future/current-adjusted
                             and retains the delisted name.

## 13. Quality Gates

| Gate | Result |
|---|---:|
| Full pytest | **830 passed** |
| Ruff | PASS |
| Strict mypy (389 source files) | PASS |
| Secret scan | PASS |
| Quant-critical regression | 31 passed |
| Performance smoke | 2 passed |

## 14. Comparison with ROUND 4

ROUND 4 concluded `PRODUCTION_READY_DEGRADED_RESEARCH` with
`SURVIVORSHIP_LIMITED` and a strict PIT universe of 9.  ROUND 7 does not change
that conclusion: the historical certification framework is now complete, but the
survivorship-safe data source is still absent, so historical research remains
non-certified and the strict production alpha universe stays 9.  The rerun
machinery is in place and will execute the full factor/walk-forward/portfolio
suite the moment a certified licensed package is imported.

## 15. Remaining Limitations

1. No licensed survivorship-safe historical dataset is installed; the framework
   is ready to certify one when available (CRSP / Norgate / MassInvestor require
   a license).
2. `SURVIVORSHIP_LIMITED` persists; historical OOS is not survivorship-safe.
3. The strict certified PIT total-return tier remains 9 names.
4. Live capital remains manual; auto execution is disabled.

## Final Verdict

**HISTORICAL_PIT_LIMITED**

The ROUND 7 provider abstraction, ingestion contract, certification framework,
permanent identifiers, dataset versioning, and gated rerun are complete and
fully tested.  Full historical certification is honestly withheld until a
licensed survivorship-safe data source is imported — no fake PASS was produced.
