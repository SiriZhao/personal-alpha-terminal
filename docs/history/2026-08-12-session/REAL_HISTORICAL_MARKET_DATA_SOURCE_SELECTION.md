# Real Historical Market Data Source Selection

Date: 2026-08-12

Result: **BLOCKED_EXTERNAL_DATA**

This report records the provider selection evidence for the Personal Alpha
Terminal historical US equity research contract. The ROUND 1 provider-neutral
contract and acceptance runner are reused. No second market-data framework was
created.

## 1. Recommendation

Recommended primary option:

**CRSP US Stock Databases**, through a licensed institutional/qualified
research subscription, because CRSP is the only candidate whose official
product material publicly claims permanent identifiers and an active/inactive
population with delisted securities and corporate actions.

Recommended backup option:

**Norgate Data US Stocks Platinum**, as a licensed local package that can be
used for a controlled acquisition pilot. Norgate alone does not satisfy the
full research contract because it does not provide delisting returns, direct
corporate-action details, or PIT total-return vintages.

No provider was purchased, no billing account was created, and no credential or
package was accepted on the user's behalf.

## 2. Machine-Readable Matrix

The official-evidence capability matrix is exported to:

`artifacts/latest/provider_selection_matrix.json`

Status values are:

- `YES`: officially documented capability
- `PARTIAL`: capability exists but requires package audit or reconstruction
- `NO`: explicitly not supported by official documentation
- `UNKNOWN`: not proven by official documentation
- `REQUIRES_LICENSE`: capability exists only under a confirmed license

`UNKNOWN` is never upgraded to `YES`.

## 3. Official Evidence

All statements below were checked on `2026-08-12` against official pages.

### CRSP US Stock Databases

Official URL:
[CRSP US Stock Databases](https://indexes.morningstar.com/research-data-products/crsp-us-stock-databases)

- Permanent identifiers: `YES`
  - Official statement: "PERMNO is a proprietary, permanent identifier used to
    track US-listed equities over time. Fixed for the life of a security..."
- Active/inactive population: `YES`
  - Official statement: "daily and monthly market data and corporate actions
    for more than 36,000 active and inactive securities"
- Delisting lifecycle: `YES` for population; exact delisting-return terminal
  treatment: `PARTIAL`
- Historical project membership: `PARTIAL`
- Corporate actions: `PARTIAL`
- PIT corporate-action availability: `UNKNOWN`
- PIT total-return vintages: `PARTIAL`
- Benchmark same-PIT compatibility: `UNKNOWN`

The public page does not prove the exact licensed data dictionary, action
announcement timing, delisting-return convention, or benchmark vintage contract.

### Norgate Data US Stocks Platinum

Official URLs:
[stockmarketpackages.php](https://norgatedata.com/stockmarketpackages.php),
[data-package-faq.php](https://norgatedata.com/data-package-faq.php)

- Delisted securities: `PARTIAL`
  - Official statement: Platinum "includes access to delisted securities and
    historical index constituents"; "Historical data back to 1990"
- Permanent `assetid`: `PARTIAL`
  - Official FAQ confirms `assetid` survives symbol changes, OTC transitions,
    delisting, and other corporate actions in supported environments.
- Ticker history: `NO`
  - Official FAQ: "Do you provide prior symbols used by a security? No, only
    the current symbol is provided."
- Listing lifecycle: `PARTIAL`
  - Official FAQ: "Major Exchange Listed" timeseries is provided, but exact
    historical exchange names are not.
- Delisting return: `NO`
  - Official FAQ: "Norgate Data does not provide any information about a
    delisting."
- Corporate actions directly: `NO`
  - Official FAQ: actions are incorporated into adjusted price data.
- Historical index membership: `PARTIAL`
  - Official FAQ provides true/false membership queries through supported
    environments, but no constituent lists or announcement dates.
- PIT total-return vintages: `NO`
- SPY/QQQ same-PIT benchmark: `UNKNOWN`

Norgate is useful as a local acquisition pilot but cannot certify the full
contract alone.

### Massive / Polygon

Official URLs:
[Market Data Terms of Service](https://massive.com/legal/market-data-terms-of-service),
[All Tickers](https://massive.com/docs/rest/stocks/tickers/all-tickers),
[Stocks Flat Files Overview](https://massive.com/docs/flat-files/stocks/overview)

- Non-display strategy use: `REQUIRES_LICENSE`
  - Official ToS states market data is "strictly for display use only" unless
    otherwise licensed and prohibits using market data to create derivative
    works including "investment strategy" without a license.
- Delisted ticker discovery: `PARTIAL`
  - Official All Tickers documentation exposes `active`, `delisted_utc`, CIK,
    FIGI, and a point-in-time `date` query.
- Permanent identity contract: `PARTIAL`
- Historical broad-universe membership: `UNKNOWN`
- Delisting returns and terminal treatment: `UNKNOWN`

### EODHD

Official URL:
[Delisted Stock Companies Data](https://eodhd.com/financial-apis/delisted-stock-companies-data-2)

- Delisted symbols: `PARTIAL`
  - Official statement: "When a company is acquired, goes bankrupt, or
    otherwise leaves an exchange, its ticker is delisted, but its historical
    data does not disappear from EODHD."
- Data availability by delisted date: `PARTIAL`
  - After 2018: EOD, Fundamentals, Dividends and Splits
  - Before 2018: EOD only
- Ticker change history: `PARTIAL`
  - Symbol Change History is US-only.
- Terminal return or delisting consideration: `UNKNOWN`
- PIT broad-universe membership: `NO`
- PIT corporate-action availability: `UNKNOWN`

### Alpaca

Official URL:
[Corporate Actions API](https://docs.alpaca.markets/us/reference/CorporateActions-1)

- Corporate-action types: `PARTIAL`
  - The endpoint documents splits, dividends, mergers, redemptions, name
    changes, worthless removals, and other types.
- Strict PIT corporate-action availability: `NO`
  - Official warning: "Currently Alpaca has no guarantees on the creation time
    of corporate actions... corporate actions may not be available immediately
    after they are announced."
- Delisted lifecycle and terminal returns: `UNKNOWN`
- Historical broad-universe membership: `UNKNOWN`

### Free Current Sources

- Nasdaq Trader current symbol directories: `NO` for historical universe
- Alpha Vantage listing status: `PARTIAL`; since 2010, but not complete PIT
  membership or delisting-return evidence
- Tiingo EOD: `PARTIAL` for per-symbol history, `NO` for PIT broad universe
- Twelve Data: `UNKNOWN` for delisted coverage and delisting returns

Current directories, current index constituents, and free current-ticker
backfills cannot reconstruct a survivorship-safe historical universe.

## 4. Selection Logic

Selection priority:

1. survivorship safety
2. delisted securities
3. permanent identifiers
4. historical membership
5. PIT corporate actions
6. delisting return
7. PIT total-return convention
8. benchmark compatibility
9. 2018-07-03 through required end coverage
10. license compatibility
11. reproducibility
12. price

Price is deliberately last.

## 5. Provider Combination Rule

A provider combination is acceptable only if it can produce one normalized
dataset with:

- a unique permanent security identity reconciliation
- ticker history and listing/delisting lifecycle
- terminal price/return
- PIT corporate-action availability
- PIT total-return convention
- same-convention SPY/QQQ benchmark
- a single `research_dataset_content_hash` and full provenance

Ticker-only joins are not acceptable.

## 6. Real vs Fixture/Test Evidence

**Real evidence in this round:** official public provider documentation, local
live-only inventory, and the absence of a licensed market-data package.

**Fixture/test evidence:** isolated unit tests for provider acceptance,
adapter mapping, raw landing-zone integrity, duplicate rows, resume, PIT
rejection, and content hashing. Those tests do not certify any provider package.

## 7. Exact User Action Required

The project needs a licensed package or package trial that allows:

- local storage of licensed data
- derived personal research artifacts
- permanent security identity
- delisted lifecycle and terminal treatment
- PIT corporate actions
- PIT total-return vintages
- SPY/QQQ with the same PIT convention

Credential/package requirement:

- CRSP: licensed file delivery or platform access under a research data
  agreement
- Norgate: US Stocks Platinum package plus export access and confirmation that
  the trial EULA permits local derived research

Until one of these packages is installed and passes `accept_research_provider`,
the legal outcome is:

`BLOCKED_EXTERNAL_DATA`
