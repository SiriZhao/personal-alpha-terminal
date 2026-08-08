# Quant Engine Core Audit — Part 1

Date: 2026-08-08  
Scope: source code, database models, migrations and tests; README claims were not treated as evidence.

## Executive result

Part 1 converts the core from an explainable but unsafe score-oriented path into a fail-closed research pipeline. The implementation now has explicit point-in-time selection, robust cross-sectional factor processing, expected-excess-return Alpha contracts, model validation states and decision-time production gates.

This is not a real-data production approval. Historical US universe membership, corporate actions and point-in-time total-return data have not completed independent certification. The live decision path must therefore remain blocked until those data gates pass.

## Actual source call chain audited

1. Provider adapters normalize raw records and persist source/ingestion metadata.
2. `ResearchDataGate` authorizes a declared purpose and rejects datasets without the required lineage, timestamps, adjustment policy and quality evidence.
3. PIT selectors choose fundamental vintages and universe snapshots visible at the information cutoff.
4. Price/fundamental features enter the cross-sectional factor pipeline.
5. Validated factor/event/probability evidence is converted to `AlphaSignal` in expected excess return space.
6. `UnifiedAlphaEngine` admits only unexpired, PIT-valid, data-valid, `PRODUCTION_APPROVED` signals.
7. A separately validated portfolio constructor produces a target; the risk engine may reduce or veto it.
8. The decision service records a manual review candidate. It does not create orders or execute transactions.
9. Historical backtests remain separate and must use PIT universes, next-tradable execution and explicit cost models.

No production module is allowed to turn a technical indicator or presentation score directly into BUY/SELL or target weight.

## Findings and changes

### Point-in-time data

- Fundamental selection requires `fiscal_period_end`, `filing_date`, `publication_time`, `available_at`, `ingested_at`, `revision_id` and `data_version`.
- A historical query selects only vintages whose `available_at` is no later than the information cutoff. A deliberately perfect future revision is invisible before publication in the leakage fixture.
- Factor persistence now reads `FundamentalVintage`, not the latest legacy `Financial` row.
- Universe membership is loaded from the latest snapshot visible at the cutoff. Current `Stock.is_active` is no longer accepted as a historical universe.
- Missing or uncertified historical universe data returns `SURVIVORSHIP_BIAS_RISK`; it is not silently reconstructed from today's listings.
- Regime breadth uses the PIT universe timeline rather than current active stocks.

### Data-quality semantics

Core feature and Alpha contracts use explicit states: `VALID`, `INSUFFICIENT_DATA`, `BLOCKED`, `NOT_VALIDATED` and `SURVIVORSHIP_BIAS_RISK`. Missing critical observations are excluded or invalidate the signal; they are never replaced by zero.

The independent real-data certification gate remains blocked because current free-provider data have not proved complete historical membership, delistings, point-in-time corporate actions and immutable total-return reconstruction.

### Factor engine

- Cross-sectional processing is performed per as-of date only.
- Percentile winsorization, MAD clipping and robust z-scores are configurable.
- Missing factor values remain missing; minimum coverage and confidence penalties are explicit.
- Within-sector centering and log-size residualization are available to measure and reduce unintended sector/size exposures.
- 12–1 momentum skips the latest month; trend uses an independent log-price slope and fit quality; volatility is independently calculated.
- The existing equal-group composite is retained only as a research explanation and is explicitly not production eligible.

Formal factor evaluation now reports Pearson IC, Spearman Rank IC, mean/std IC, ICIR, positive-IC ratio, quantile returns, top-minus-bottom spread, long-only top return, turnover, hit rate, rolling IC, sector/regime stability and 1/5/10/20/40/60/120-day decay with peak horizon and approximate half-life.

### Regime engine

The existing causal regime feature engine and walk-forward calibration were retained, but breadth was corrected to PIT membership. Calibration reports Brier score, log loss and calibration bins against a naive baseline. If independent OOS calibration is ineligible or fails, output remains score/research-only and cannot enter production Alpha.

### Conditional probability and event/relationship evidence

Conditional evidence now reports baseline and conditional probability, probability lift, odds ratio, baseline and conditional expected return, expected-return lift, credible interval and sample size. Small samples are invalid and shrunk rather than promoted.

Probability validation includes OOS Brier/log-loss comparison and chronological stability. Event validation adds horizon decay, half-life, subperiod/regime stability and overlap-key rejection. Relationship validation distinguishes statistically significant research edges from after-cost, OOS-stable Alpha candidates. Neither an event result nor a graph edge is automatically production Alpha.

### Unified Alpha and decision path

Each `AlphaSignal` records symbol, as-of, signal type, expected excess return, horizon, raw/normalized signal, confidence, sample/statistical/economic strength, half-life, expiry, data/PIT status, model version and data version.

Allowed validation states are `RESEARCH`, `VALIDATING`, `TESTED`, `PRODUCTION_APPROVED` and `DISABLED`. Only `PRODUCTION_APPROVED` enters daily decisions.

The former magic weighted score path was removed from production decisions. `quant_score` is now presentation metadata only. A candidate is blocked unless it has:

- calibrated and sufficiently sampled OOS evidence;
- production-approved Alpha and expected excess return;
- valid PIT/data versions;
- a production-approved portfolio target;
- applied risk constraints.

There is currently no independently certified production target-weight constructor. This is an intentional remaining block, not an implicit equal-weight fallback.

### Paper trading removal

Paper accounts, cash ledgers, orders, fills, positions, transactions, valuations, decisions, reconciliation services, screens, commands, configuration and tests were removed from active source. Accept/reject/watch records only manual decision history and does not mutate holdings.

Existing user databases may still contain inert historical paper tables. They are not dropped automatically because destructive deletion of user data requires an explicit migration policy. New schema heads do not create them.

## Legacy and duplicated logic

- Older individual factor modules and adaptive-sleeve heuristics remain for research compatibility; they are not production-approved Alpha.
- Event study, conditional probability and market graph services still have research/reporting paths independent of the unified Alpha adapter. They cannot affect production decisions until an explicit validated adapter is added.
- Historical Streamlit/TUI and old build artifacts are outside this core reconstruction and were not repackaged. They must not be treated as evidence of the new runtime.
- Editing historical Alembic revisions was inherited from the working tree. The new head adds the validation-state constraint, but production migration rehearsal remains required.

## Verification status

Final local verification on 2026-08-08:

- full pytest suite: **378 passed**, with two third-party Backtrader `SyntaxWarning` messages;
- Ruff on the changed quant/application/regime/factor/TUI/test scope: **passed**;
- mypy strict on 56 affected source files: **passed**;
- `pip check`: **passed**.

These results establish deterministic fixture and integration behavior. They do not certify the economic validity of Alpha on real historical data.

Implemented and fixture-tested:

- PIT vintage selection and future-information exclusion;
- PIT universe selection and explicit survivorship-risk status;
- factor winsorization, normalization, missingness and neutralization;
- momentum/trend/quality/volatility factor paths;
- factor IC and decay metrics;
- regime PIT breadth and calibration behavior;
- probability lift, expected-return lift, calibration and stability;
- event decay/stability and relationship tradability gates;
- Alpha validation states and production admission;
- manual decision history without simulated execution.

Blocked or not validated on certified real data:

- historical US constituents including delistings and symbol histories;
- PIT corporate-action ledger and total-return reconstruction;
- fundamental-vintage completeness across a real research universe;
- calibrated regime superiority on locked real OOS windows;
- factor/Alpha economic value after costs on locked real OOS data;
- production portfolio construction approval;
- PostgreSQL migration/recovery rehearsal for this schema head.

## Release decision

Engineering status: ready for continued Part 2 development.  
Investment/live-decision status: **BLOCKED**.  
Reason: data certification and real OOS model approval are incomplete; no Alpha or target portfolio may be represented as production-ready.
