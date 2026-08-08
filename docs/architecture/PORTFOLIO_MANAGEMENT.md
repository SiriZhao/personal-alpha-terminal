# Portfolio Management

## Scope

This module is a local analytical ledger, not a broker and not an order-management system.
It supports long-only stocks, ETFs, bonds, money-market funds, gold, commodities, and
multi-currency cash. It does not transmit, queue, or simulate executable orders.

## Ledger events

`portfolio_transactions` is append-oriented and records:

- `buy` and `sell`: positive quantity, execution price, fee, currency, and FX rate to the
  portfolio base currency;
- `dividend`: cash received, with optional withholding recorded in `fee_amount`;
- `fee`: standalone custody, platform, or tax charge;
- `deposit` and `withdrawal`: external capital flows excluded from investment return;
- `split`: split ratio in `quantity`, including reverse splits with a ratio below one.

Every event has `event_time`, `available_time`, and `ingested_time`. Broker imports should
provide a stable `source + external_id`; repeats are idempotent. `settlement_date` is kept for
cash-control and reconciliation, while holdings and performance change on the execution
`trade_date`.

## Return convention

The engine reconstructs quantities and cash chronologically. It values assets with the
selected provider's unadjusted close because dividends are explicit cash events. Using an
adjusted close in this ledger would double-count dividends and is prohibited.

Daily time-weighted return uses an end-of-day external-flow convention:

```text
r_t = (ending_value_t - deposit_t + withdrawal_t) / ending_value_(t-1) - 1
```

Buys, sells, dividends, splits, and fees are internal portfolio events. Deposits and
withdrawals are external flows. The first day has no return when opening value is zero.
Annualized return compounds the daily time-weighted series using 252 observations per year.

Sharpe and Sortino use the configured annual risk-free rate converted to an effective daily
rate. Beta is covariance with the base-currency benchmark divided by benchmark variance.
Jensen Alpha is the annualized daily intercept:

```text
alpha = 252 * (mean(Rp) - Rf - beta * (mean(Rb) - Rf))
```

Beta and Alpha are withheld below the configured aligned-sample minimum.

## FX and valuation

Transaction FX is immutable evidence of the conversion used for that cash event. Daily
valuation separately uses `fx_rates` and rejects rates or prices beyond configured staleness
limits. Currency exposure includes both securities and cash.

## Allocation and rebalancing

Versioned targets live in `portfolio_allocation_targets` and must sum to 100%. The engine
compares current and target weights and reports only differences that exceed both drift and
value thresholds. Indicative values omit taxes, spreads, liquidity, lot size, and investor
suitability, so they are not trade instructions.

## Required reconciliation

Before relying on a report, reconcile ledger cash, quantities, dividends, fees, splits, and
FX against the broker statement. A missing event invalidates performance. Delisted assets and
corporate actions still require complete raw prices and explicit ledger adjustments.

## Known limits

- no shorting, margin, leverage, derivatives, tax-lot accounting, or tax optimization;
- close-to-close valuation cannot precisely attribute intraday execution timing;
- a static benchmark is not automatically the correct benchmark for every asset mix;
- historical Beta and Alpha are descriptive linear statistics, not forecasts or causal proof.

