# Current Operational Universe Report

Date: 2026-08-12

## 1. Universe Source

The current operational universe is built from:

- Nasdaq Trader current symbol directory
- NYSE/Nasdaq/NYSE American current listings
- current local certified price data
- current PIT total-return series
- current trading status
- current eligibility filters from `config.yaml`

This is `CURRENT_OPERATIONAL_UNIVERSE`, not `HISTORICAL_RESEARCH_UNIVERSE`.

## 2. Funnel

Observed real counts:

- raw listed securities: `8833`
- raw listed equities: `7475`
- security-type eligible: `4957`
- data eligible: `9`
- liquidity eligible: `9`
- factor eligible: `9`
- signal eligible: `9`

The current local DB contains 18 tracked instruments. Only 9 are common-stock
equities with enough current PIT price history, raw ADV and factor lookback:

`AAPL`, `AMZN`, `GOOGL`, `META`, `MSFT`, `NVDA`, `JNJ`, `JPM`, `XOM`

## 3. Why Not Thousands

The current operational universe is not artificially capped at 18. The local
free provider architecture currently has full live history for the configured
minimum research universe only. Expanding to thousands of current securities
would require either:

- licensed historical/current market-data package
- broad-market EOD bulk download with license terms
- longer local backfill for each current ticker

This limitation is reported explicitly and is not hidden as research coverage.

## 4. Lookback

Required factor lookbacks:

- momentum: 252 sessions
- trend: 126 sessions
- volatility: 63 sessions

Each signal-eligible security has enough current PIT lookback. This is
`OPERATIONAL_LOOKBACK`, not `RESEARCH_HISTORY`.

## 5. Survivorship Boundary

No current directory row is used to claim a 2018 historical universe. No
current membership is backfilled.

## 6. Blockers

- No licensed survivorship-safe historical package.
- No CRSP/Norgate package.
- No permanent security mapping for broad universe.
- Current full-universe price coverage absent.

Therefore:

```text
CURRENT_OPERATIONAL_UNIVERSE = 9 factor-eligible securities
HISTORICAL_RESEARCH_UNIVERSE = NOT_CERTIFIABLE
```
