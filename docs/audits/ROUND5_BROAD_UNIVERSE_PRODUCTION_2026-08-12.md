# ROUND 5 — BROAD-UNIVERSE PRODUCTION ACTIVATION & FORWARD VALIDATION

Date: 2026-08-12
Branch: `codex/round5-broad-universe-production`
Baseline: ROUND 4 `PRODUCTION_READY_DEGRADED_RESEARCH` (strict PIT universe = 9)

## Executive Summary

ROUND 5 separated **Current Operational PIT** from **Historical Research PIT** and
activated the existing broad current universe (~1,959 `PRICE_BASED_RANKING`
securities) as the formal production daily factor universe. The historical
research tier stays strictly certified (9 total-return names, `SURVIVORSHIP_LIMITED`)
and is never used to collapse the current operational universe.

Final verdict: **BROAD_UNIVERSE_PRODUCTION_READY**

Real acceptance evidence:

| Quantity | Value |
|---|---:|
| Current operational universe (factor eligible) | **1,959** |
| Full factor rows computed in daily run | **1,959** |
| Historical research tier (strict) | 9 |
| Alpha-positive after factor ranking | 1,051 |
| Liquidity/risk screened | 1,047 |
| Candidates entering optimizer | 100 |
| Provisional recommendations (isolated policy) | 9 |
| Quarantined symbols excluded | 2 |
| Fills / simulated fills | 0 |

The formal daily run's factor universe expanded from **9 to 1,959** in the
production path, so the ROUND 5 hard gate is satisfied.

## 1. Two-Tier PIT Model

New explicit state in `data/us_market/broad_universe.py`:

```text
PitQualification.CURRENT_OPERATIONAL_PIT    -> production daily factor universe
PitQualification.HISTORICAL_RESEARCH_PIT    -> strict certified research tier
```

- `EligibilityRules.require_pit_total_return` selects the tier.
- `evaluate_broad_universe` now reports `qualification`, and the operational tier
  is evaluated independently of the historical tier.
- A degraded historical certification (`SURVIVORSHIP_LIMITED`, strict=9) does not
  reduce the current operational universe.

No current-data standard was lowered for `CURRENT_OPERATIONAL_PIT`. Securities
still must satisfy: current identity, exchange/security type, financial status,
real PIT price rows at decision time, no future rows, valid OHLCV, freshness,
history length (252 sessions), liquidity, factor computability, risk inputs,
current-run corporate-action continuity, symbol mapping, and quarantine.

## 2. Broad Production Universe

The daily production path (`ProductionDailyQuantInputAssembler._select_alpha_universe`)
now selects the broad current operational universe when configured
(`config.yaml` sets `universe_require_pit_total_return: false`), and reports the
strict certified tier separately as `historical_research`.

The old 9-ticker bootstrap list is no longer a production dependency: the
assembler selects from the broad current directory and the price frame comes
from PIT-filtered raw `unadjusted_ohlcv` (`USPointInTimeRepository.raw_price_frame`),
not the certified total-return series (which only the strict tier requires).

Real funnel (2026-08-12):

```text
US listed securities        8,833
Listed equities             7,475
Security type eligible      4,957 (4,955 priced)
Current data eligible       3,139
Liquidity eligible          1,959
Factor eligible             1,959
Operational tradable        1,959
Quarantined                 2
```

## 3. Candidate Compression

New `quant_engine/candidates.py`: the full ranked cross-section is reduced to a
bounded, deterministic candidate pool before portfolio optimization. Every step
records N, rejected count and reason.

Real candidate funnel (daily run `daily-c18d6fa4...`):

```text
factor_ranked     1959  (rejected 0)
alpha_positive    1051  (rejected 908 non-positive)
minimum_alpha     1051  (rejected 0)
liquidity         1047  (rejected 4)
risk_screening    1047  (rejected 0)
candidate_bound   100   (rejected 947 over bound)
```

The optimizer never receives thousands of names; the final recommendation count
is decided by portfolio/risk (9 in the acceptance run), and `0 Actions` remains a
legal result.

## 4. Cross-Sectional Production

- Ranking uses one `decision_time`.
- Winsorization/z-scoring use only the current cross-section (`process_cross_section`).
- No future rows: `raw_price_frame` filters `available_time <= decision_time` and
  `trade_date <= as_of`.
- Rank is deterministic (expected alpha descending, then symbol).
- The probability overlay remains `RESEARCH_ONLY` (ROUND 5 freezes Probability).

## 5. Forward Validation Ledger

`quant_engine/forward_track.py` now supports per-horizon immutable outcomes
(`ForwardOutcome.horizon` keyed by `recommendation_id::horizon`). The daily
workflow appends a `ForwardPrediction` for every approved recommendation:

- run_id, decision_time, symbol, target weight, expected alpha, probability,
  risk contribution, benchmark, data hash.
- Immutable: predictions are never mutated; outcomes may only be appended.
- No simulated fill: the ledger records what the system recommended, never a fill.

Real ledger after acceptance: **9 predictions, 0 outcomes, 0 fills**.

New CLI: `pat forward-track report` and `pat forward-track append-outcome`
(1D/5D/10D/H21/SPY_REL/QQQ_REL/MAE/MFE horizons).

## 6. Operational Policy

- The existing user policy (old rules fingerprint) is invalidated by the new
  universe identity — expected behavior, no new policy auto-generated.
- First acceptance: `VALID_ANALYSIS_NON_ACTIONABLE` (SIGNAL blocked,
  PORTFOLIO/RISK/DECISION/EXECUTION NOT RUN).
- Second acceptance: an **isolated** temporary policy verified the provisional
  recommendation path. The user's real policy at
  `var/operational/operational_policy.json` was **not** overwritten.
- Fail-closed: policy identity mismatch → no provisional advice.

## 7. Risk / Coverage Guards

- `quant_engine/operational_baseline.py` tracks recent operational-universe sizes.
- If the broad factor-eligible count falls below the configured minimum or
  collapses below the recent median (`coverage_collapse_ratio`), the daily run
  fails closed instead of recommending from a shrunken cross-section.
- Quarantined symbols are excluded from the current operational universe.

## 8. Data Layer Fixes

- `BroadUSUniverseService.select` now excludes quarantined securities and reports
  the quarantine count.
- Broad-synced stocks now receive `TradingStatus=TRADABLE` rows
  (`_ensure_tradable`), so broad candidates satisfy the same current tradability
  gate as certified members.
- One-time backfill: `scripts/backfill_broad_trading_status.py` created 4,946
  TRADABLE records (9 already existed).

## 9. Performance

The broad daily run completes with a 70s DATA stage (canonical certification) and
near-instant FEATURE/FACTOR/SIGNAL (1,959 rows). No full-history re-download: the
acceptance runs used `--no-refresh` against the already-backfilled DB (2,315,885
price rows, 4,955 priced stocks).

## 10. Tests Added

New files:
- `tests/unit/data/us_market/test_round5_operational_tiers.py` — two-tier
  separation, current-data gates, quarantine, determinism.
- `tests/unit/quant_engine/test_round5_candidate_compression.py` — compression
  steps, bound, determinism, min-alpha, empty pool.
- `tests/unit/quant_engine/test_round5_operational_baseline.py` — collapse and
  below-threshold fail-closed.
- `tests/integration/test_round5_broad_universe_production.py` — broad universe
  replaces bootstrap list, future-row poison, policy identity invalidation.
- Extended `tests/unit/quant_engine/test_forward_track.py` — per-horizon outcome
  immutability, prediction immutability.

Covered requirements: broad production universe, no bootstrap leakage, universe
funnel, current operational PIT vs historical certification separation, data
quarantine, sudden coverage collapse, cross-sectional determinism, future-row
poison, universe identity, OperationalPolicy invalidation, forward prediction
immutability, outcome append, no simulated fill, portfolio unchanged without
explicit fill (existing `test_e2e_i...`).

## 11. Quality Gates

| Gate | Result |
|---|---:|
| Full pytest | **795 passed** |
| Ruff | PASS |
| Strict mypy (381 source files) | PASS |
| Secret scan | PASS |
| Quant-critical regression | 31 passed |
| Performance smoke | 2 passed |

## 12. Acceptance Runs

Run 1 (no valid policy): `daily-c18d6fa401ac4a6daf15bb38c63b1bf8`
- Classification: `VALID_ANALYSIS_NON_ACTIONABLE`
- FACTOR: 1,959 cross-sectional observations (was 9)
- PIT: PASS; DATA: PASS; SIGNAL: BLOCKED (strategy not approved)
- Ledger unchanged; portfolio unchanged.

Run 2 (isolated provisional policy `operational-policy-4532a8b12b6bf79a820b`):
`daily-3097ad8629484da397ccfc67d475b281`
- Classification: `PROVISIONAL_ACTIONABLE`
- Operational universe: 1,959; candidates: 100; recommendations: 9
- 9 immutable forward predictions recorded; 0 fills.

## 13. Remaining Limitations

1. Historical research certification remains `DEGRADED — SURVIVORSHIP_LIMITED`;
   the strict tier stays at 9 until licensed survivorship-safe history (ROUND 7).
2. Probability remains `RESEARCH_ONLY` with no target-weight incremental value.
3. Market-cap/sector metadata for full size neutralization remains unavailable.
4. The operational path is provisional and gated by an explicit user policy;
   recommendations require manual review and manual Charles Schwab execution.
5. Forward outcomes require real future observations to be appended over time.

## Final Verdict

**BROAD_UNIVERSE_PRODUCTION_READY**

The formal daily-run factor universe expanded from 9 to 1,959 without lowering
current-data correctness. The broad CURRENT_OPERATIONAL_PIT universe, candidate
compression, coverage guards, quarantine handling, immutable forward validation
ledger, and fail-closed operational policy handling are all in place and verified
on real data. Live capital remains manual and disabled; no simulated execution
exists.
