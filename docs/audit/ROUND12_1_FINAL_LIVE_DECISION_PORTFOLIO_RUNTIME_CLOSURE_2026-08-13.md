# ROUND 12.1 FINAL - Live Decision Semantics, Portfolio Cardinality, Size Risk & Runtime Closure

Date: 2026-08-13

Verdict: `ROUND12_1_CODE_READY_AWAITING_EXPLICIT_POLICY_RENEWAL`

## Executive conclusion

The Round 12.1 code, terminal semantics, diagnostics, and regression gates are
complete. The existing `ALLOW_PROVISIONAL` policy is correctly invalidated by
the source/config identity change and now reports `IDENTITY_MISMATCH`. No policy
was renewed and no live actionable acceptance is claimed.

The operator must explicitly run:

```text
python main.py operational-policy create --decision ALLOW_PROVISIONAL
```

Only after that interactive confirmation may the final real live-refresh
acceptance be evaluated.

## 1. Why final holdings were 10

Code-level finding: there was no fixed top-10 optimizer constraint.

- Broad candidate compression is `universe_candidate_max = 100`.
- `compress_candidates` ranks the full factor cross-section by expected alpha,
  applies liquidity/risk gates, then bounds the pool to 100.
- Portfolio optimization receives the compressed candidate signals, not a
  hard-coded alpha top 10.
- `[:10]` occurs only in terminal candidate display and trace display; it does
  not enter portfolio construction or trade generation.
- Final target holdings are the result of position cap, liquidity caps, gross
  exposure, volatility, beta, sector, cluster, turnover, HHI, size, and no-trade
  constraints.
- The observed 10 holdings were therefore an optimizer result, not a direct
  alpha rank cut.

A canonical `maximum_holdings: 10` portfolio parameter was added as a
post-optimization fail-closed guard. If the optimizer ever produces more than
10 holdings, the pipeline blocks with `MAX_HOLDINGS_EXCEEDED`; it never silently
truncates by factor rank. `portfolio_max_holdings: 10` is now in `config.yaml`
and affects the portfolio constraint hash.

Terminal PIT/Universe output now shows:

- candidate pool
- optimizer input
- maximum allowed holdings
- optimized target holdings
- risk-engine security count
- final decision holdings
- explicit `Pre-optimizer Top10 = false`

## 2. Probability and confidence null semantics

Probability fallback is now `None`, not `0.0`.

- `confidence_score` is nullable in the decision database model and migration
  `a7d1f4c2b9e3`.
- Trade evidence and proposals carry nullable confidence.
- `TodayRecommendation`, `DecisionRow`, JSON persistence, forward ledger, and
  terminal rendering preserve `None`.
- Fallback confidence renders as `N/A`.
- Confidence source renders as `NOT_CALIBRATED`.
- Base Alpha and probability production influence were not changed.

## 3. Size exposure and size-tilt diagnostics

The risk model now carries raw candidate market-cap metadata and observational
size diagnostics without changing factor, alpha, portfolio, or risk formulas.

Current real strict assembler evidence:

- candidate optimizer input: 5
- risk metadata rows: 11
- valid PIT market-cap rows: 0
- missing market-cap rows: 5
- coverage ratio: 0.0
- user-facing status: `SIZE_EXPOSURE_UNAVAILABLE`
- internal risk status: `NOT_VALIDATED`

This correctly blocks production portfolio construction. If an explicit valid
operational policy is later active, the operational path remains degraded and
records `size_neutralization:degraded`; it does not silently assume a valid size
neutralization.

Diagnostics include optimizer input, market-cap valid/missing counts, coverage
ratio, candidate/final weighted average and median, size percentiles, size
bucket counts, small/micro exposure, smallest holding cap, liquidity
percentile, ADV, spread proxy, and expected market impact. Missing values remain
explicit `N/A`, and current market cap is never backfilled as historical PIT
evidence.

## 4. Market refresh taxonomy

Generic `PARTIAL` wording was removed.

Supported statuses:

- `LIVE_REFRESH_PASS`
- `LIVE_REFRESH_PASS_WITH_QUARANTINE`
- `LIVE_REFRESH_DEGRADED_PROVIDER`
- `LIVE_REFRESH_PARTIAL_COVERAGE`
- `LIVE_REFRESH_FAIL`

Daily DATA evidence now shows requested securities, actual refresh, cache
reuse, provider returned, certified coverage, quarantine, provider incidents,
and coverage collapse. Real delisted/no-price symbols such as SVA/MDV are
quarantine evidence, not automatically provider outages.

## 5. Execution semantics

Execution plan and broker execution are strictly separated.

- plan status: `READY`, `NO_ACTION`, or `BLOCKED`
- broker execution: `NOT_EXECUTED`
- execution mode: `MANUAL_ONLY`
- broker: Charles Schwab
- broker API: `DISABLED`
- `execution_plan_generated=true` when a plan exists
- `broker_order_submitted=false`
- `auto_execution=false`
- `manual_execution_only=true`

No broker API was added.

## 6. Doctor

`python main.py doctor` now reports sanitized checks for Python interpreter and
version, virtual environment, `exchange_calendars`, OpenAI SDK, database,
market-data storage, intelligence raw corpus/events, SEC User-Agent
PRESENT/MISSING, DeepSeek credential PRESENT/MISSING, DeepSeek connectivity,
OperationalPolicy state/identity, report and `var` writability, timezone, and
system clock. Secret values and the SEC User-Agent value are never printed.

## 7. Light Chinese localization

Updated user-facing headings include:

- final validated decisions
- rejected signals/gate blockers
- decision formation process
- execution plan
- probability assessment
- size tilt diagnostics
- market refresh evidence

Machine status codes and BUY/SELL/HOLD/NO_TRADE remain unchanged.

## 8. Round 13.2 preservation

Round 13.2 AI/PIT evidence remains intact:

- Raw SEC landing documents: 44
- Database raw documents: 44
- PIT-certified: 44
- Issuer-resolved: 44
- Security-mapped: 24
- DeepSeek connectivity: AVAILABLE
- Accepted events: 18
- SHADOW features: 15 / database 30
- Production influence: NONE
- `intelligence audit`: PASS

## 9. Quality gates

- Full pytest: `941 passed`
- Quant-critical regression: `31 passed`
- Ruff: PASS
- Strict mypy: PASS, 417 source files
- Secret scan: `SECRET_SCAN_PASS`
- Doctor smoke: PASS
- Intelligence audit: PASS
- Daily no-refresh renderer smoke: completed as
  `VALID_ANALYSIS_NON_ACTIONABLE` because policy identity mismatch correctly
  blocks production advice

## 10. Operational policy evidence

`python main.py operational-policy status` reports:

- status: `IDENTITY_MISMATCH`
- effective: `false`
- reason: `OPERATIONAL_POLICY_IDENTITY_MISMATCH`
- mismatched fields: `code_config_fingerprint`, `portfolio_config_hash`

This is expected after the Round 12.1 source/config change. It was not renewed.

## Final disposition

`ROUND12_1_READY` is not claimed because the final live-refresh actionable
acceptance requires the user to explicitly sign the new current identity. The
code and quality-gate portion is complete.

Required operator action:

```text
python main.py operational-policy create --decision ALLOW_PROVISIONAL
```

Then rerun:

```text
python main.py daily
```
