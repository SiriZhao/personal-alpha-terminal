# ROUND 10 — LIVE MARKET DATA RELIABILITY & DAILY REFRESH CLOSURE

Date: 2026-08-13
Branch: `codex/round10-live-market-data-reliability`
Baseline: ROUND 9 `LLM QUANT MODERNIZATION PASS` (commit `754b630`, pushed)

## Final Verdict

```text
LIVE_MARKET_DATA_READY_DEGRADED
```

The production live-refresh path is now reliable and evidence-backed:
- Yahoo MultiIndex/Close root cause fixed with canonical normalization.
- AFRM and all canary symbols return real OHLCV.
- Stooq browser challenge no longer causes per-ticker repeated retries
  (provider circuit breaker trips and suppresses requests).
- Broad universe refreshes with LIVE REFRESH at 100% coverage.
- The full daily run completes on fresh data (`VALID_ANALYSIS_NON_ACTIONABLE`
  due to a POLICY block, not a data failure).

The verdict is DEGRADED (not fully READY) because Stooq is currently
bot-challenged and is therefore demoted to OPTIONAL/research fallback; Yahoo is
the only live primary at this time.

## 1. Original Failure

Real broad-market daily refresh produced:

```
Yahoo Finance: Provider response is missing columns: ('Close', 'close')
  (AEXA, AFCG, AFRI, AFRM ...)
Stooq: HTML/JavaScript browser challenge returned
All providers failed for US/stock/<symbol>
```

## 2. Yahoo Root Cause (real reproduction)

With yfinance 1.5.2 + pandas 3.0.5 on live data:

- **Single ticker** + `multi_level_index=False` -> single-level columns
  `['Adj Close','Close','High','Low','Open','Volume']`, Close present.
- **Batch (multiple tickers)** + `multi_level_index=False` -> yfinance **ignores
  the flag when `len(tickers) > 1`** and returns **MultiIndex columns**
  `('Close', 'AFRM')` etc.
- The old `_flatten_columns` took `column[0]` naively, producing duplicate
  column names; `row['Close']` then returned a **Series**, and
  `_to_decimal(Series)` produced **NaN Close** (silent corruption) or, with the
  other MultiIndex ordering, a real Close was misreported as missing.

Evidence: `probe_yahoo.py` showed batch frame `shape=(29, 36)`,
`is_multiindex=True`, `close_value` as a per-ticker Series; the old
`frame_to_raw_bars` produced `bars: 29, first bar close: NaN`.

## 3. Stooq Root Cause (real reproduction)

Live probe of `StooqStockAdapter.fetch_raw` for SPY and AFRM both raised:

```
ProviderRequestError: Stooq is unavailable: HTML/JavaScript browser challenge returned
```

This is a provider-level BOT_CHALLENGE incident. The previous design retried it
per symbol × thousands of symbols, which is the catastrophic
O(N × retries × providers) path.

## 4. Changes Made

- `data/market_data/providers/canonical.py` (new): canonical OHLCV normalization
  with per-ticker MultiIndex extraction (both Price/Ticker and Ticker/Price
  orderings), single/batch, casing, missing/NaN Close rejection (never silent),
  timezone-aware indexes, empty/partial responses, duplicates preserved for
  downstream dedup.
- `data/market_data/providers/common.py`: `frame_to_raw_bars` now delegates to
  the canonical module (used by Yahoo, Stooq, AKShare).
- `data/market_data/error_classification.py` (new): full taxonomy
  (SYMBOL_NOT_FOUND, NO_PRICE_HISTORY, SCHEMA_CHANGED, MALFORMED_RESPONSE,
  RATE_LIMITED, TIMEOUT, TRANSIENT_NETWORK, HTTP_BLOCKED, BOT_CHALLENGE,
  AUTH_REQUIRED, STALE_RESPONSE, PARTIAL_RESPONSE, PROVIDER_UNAVAILABLE,
  DATA_QUALITY_FAILURE, UNKNOWN_PROVIDER_ERROR) with retryable flags and
  sanitized structured error records.
- `data/market_data/circuit_breaker.py` (new): provider circuit breaker
  (HEALTHY/DEGRADED/OPEN_CIRCUIT/RECOVERING) that trips on N consecutive
  structural failures or a sustained failure rate, suppresses bulk requests on
  OPEN_CIRCUIT, and recovers via health probe.
- `data/market_data/canary.py` (new): canary smoke (SPY/QQQ/AAPL/MSFT/NVDA/
  AMZN/META/GOOGL/AFRM) distinguishing SYMBOL_QUARANTINE from PROVIDER_INCIDENT.
- `data/market_data/health_report.py` (new): daily provider health + coverage
  report with baseline comparison and fail-closed coverage-collapse verdict.
- `data/market_data/service.py`: circuit-aware provider routing, classified
  retry policy (only retryable classifications), provider outcome/latency
  recording, and a **batch-first refresh** path for large universes
  (partial success persisted per chunk; fresh symbols skipped for resume).
- `data/market_data/factory.py`: constructs the circuit breaker + batch provider
  for the daily engine.
- `data/broad_market/service.py`: circuit-aware broad sync that stops chunk
  requests on OPEN_CIRCUIT and reports `provider_incident` instead of
  per-symbol quarantine for provider-level failures.
- `terminal/daily_renderer.py` + `application/daily_orchestrator.py`:
  DATA MODE (`LIVE_REFRESH` / `CACHE_REPLAY`) in provenance and a
  【市场数据】 panel (trade/analysis date, expected/actual latest session,
  data mode, primary/fallback provider, coverage, verdict).

## 5. Provider Architecture

```text
Universe -> symbol mapping -> batch partition -> primary provider bulk request
 -> normalize (canonical) -> validate -> persist successes -> collect failures
 -> fallback only for retry-eligible -> quarantine / failure manifest
```

## 6. Retry Policy

Retryable: TIMEOUT, TRANSIENT_NETWORK, RATE_LIMITED, PARTIAL_RESPONSE,
PROVIDER_UNAVAILABLE, UNKNOWN_PROVIDER_ERROR (exponential backoff + jitter).
Not retried: BOT_CHALLENGE, SCHEMA_CHANGED, AUTH_REQUIRED, HTTP_BLOCKED,
SYMBOL_NOT_FOUND, NO_PRICE_HISTORY, MALFORMED_RESPONSE, DATA_QUALITY_FAILURE.

## 7. Circuit Breaker

- Trips after `trip_threshold` consecutive structural failures or a sustained
  failure rate (min 10 observations) in the window.
- `OPEN_CIRCUIT` suppresses further bulk requests for that provider.
- `RECOVERING` allows a health probe; success returns to HEALTHY.
- Persisted under `var/cache/providers/circuit-breaker/` (git-ignored).

## 8. Batch Architecture

- Daily engine batch-first for universes > 200 symbols (bounded chunks,
  per-chunk commit, partial success, resume via fresh-symbol skip).
- Broad sync: chunked batch download with per-chunk isolation, idempotent
  upsert, per-symbol quarantine only for genuine symbol failures.

## 9. Coverage Before / After

ROUND 5 baseline: priced ~4,955, factor eligible ~1,959.

Real LIVE REFRESH (this round):
- Canary (9 symbols): 9/9 real Close, latest completed session 2026-08-12.
- 100-symbol: 100/100 coverage, 0 failed, 741 bars, 96 inserted, 37.95s.
- Broad (4,957 requested): 4,956 received, coverage 1.000, 73,966 bars,
  3,578 inserted, 1 quarantined (SVA - genuinely delisted), no provider incident.
- Full daily run: DATA PASS, PIT PASS, FACTOR **2,129** cross-sectional
  observations (fresh live refresh improved coverage above the 1,959 baseline).

## 10-13. Acceptance Results

- **A Canary**: PASS (all 9 symbols real OHLCV, no future rows).
- **B 100 symbols**: PASS (coverage 1.000, 0 failed).
- **C Broad universe LIVE REFRESH**: PASS (coverage 1.000, only genuine
  delisted symbol quarantined).
- **D Full daily run LIVE REFRESH**: PASS — `VALID_ANALYSIS_NON_ACTIONABLE`
  from a POLICY block (SIGNAL: STRATEGY_NOT_PRODUCTION_APPROVED), not a data
  failure; `data_mode=LIVE_REFRESH`, DATA coverage 1.0, PIT integrity PASS,
  future_rows 0.

## 14. Test Results

- Full pytest: **891 passed** (869 + 22 new)
- New tests: canonical normalization (MultiIndex both orders, missing Close,
  NaN Close, empty, casing, missing Adj Close, timezone, duplicates), error
  classification, circuit breaker (trip/block/recover), canary incident vs
  symbol-level, coverage collapse fail-closed, provider health summary, engine
  circuit suppression, batch-first persistence.
- Ruff PASS; strict mypy (410 source files) PASS; secret scan PASS;
  quant-critical 31; performance 2.

## 15. Remaining Limitations

1. Stooq is currently bot-challenged and demoted to OPTIONAL/research fallback;
   Yahoo is the only live primary.  The circuit breaker prevents O(N) retries
   and allows recovery probes.
2. Live market-data readiness is `DEGRADED` until a second reliable live source
   is available.
3. Full broad refresh wall-clock is dominated by Yahoo batch latency; bounded
   concurrency is deliberately conservative to avoid provider blocking.
4. Live capital remains manual; auto execution disabled.

## Final Verdict

**LIVE_MARKET_DATA_READY_DEGRADED**

No data-quality standard was lowered.  The Yahoo schema root cause is fixed with
real evidence, Stooq's bot challenge no longer triggers per-ticker retry storms,
the circuit breaker is active, broad universe refreshes with real LIVE REFRESH
at 100% coverage with no abnormal collapse, the full daily run completes on
fresh data, and ROUND 5-9 behavior is preserved.
