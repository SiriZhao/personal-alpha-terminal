# Research Data Foundation Report

## Technical summary

**Classification: `NOT_CERTIFIABLE`.** The project now has an isolated, provider-neutral
historical research package contract and a reproducible CSV/Parquet/SQLite
`Raw -> Normalize -> Manifest -> Certify -> Dataset` path. No available live provider supplies
the historical membership, lifecycle, identifier, and PIT corporate-action evidence required
for production Alpha certification, so `USAdaptiveAlphaCoreV1` remains `DIAGNOSTIC_ONLY`.

## Current local evidence

| Item | Observed evidence | Certification interpretation |
| --- | ---: | --- |
| Live raw price range | 2024-08-07 to 2026-08-10 | Live analysis only |
| Live price rows / securities | 9,055 / 18 | Not survivorship-safe research coverage |
| Universe snapshots / membership rows | 2 / 36 | 2026-08-07 and 2026-08-10 current snapshots only |
| Historical identifier rows | 0 | Incomplete |
| Known delisted securities | 0 | Coverage unknown, not evidence of zero delistings |
| Corporate actions | 3 cash dividends | Lifecycle and full PIT history incomplete |
| Live PIT total-return versions | 180 across 18 securities | Daily-domain versions; current-universe history is not research certification |
| Persisted research exchange sessions | 0 | Dataset-bound calendar incomplete |
| XNYS reference calendar | 503 sessions / 5 early closes | Rules verified for 2024-08-07 to 2026-08-10, but not a certified research package |
| Production approval records | 0 | No strategy promotion |

The live price dates are real local observations, but historical membership coverage is 0% for
a certifiable backtest period: two current snapshots cannot answer who was eligible on an
arbitrary historical date. Delisting-return coverage is unmeasurable because no authoritative
delisting population or terminal-return ledger is present.

## Contracts and validation

The data model uses a permanent security ID with non-overlapping ticker vintages, exchange,
listing/delisting dates, reason when supplied, and `US_EQUITY` / `US_ETF` / `BENCHMARK` type.
Membership carries effective and availability intervals. The validator rejects future prices,
future membership, future corporate actions, current-snapshot backfill, orphan identities,
mixed ETF/equity/benchmark universes, overlapping ticker vintages, duplicate/incorrect XNYS
sessions, and unexplained price termination. A missing delisting return remains `None` and adds
`DELISTING_RETURN_UNAVAILABLE`.

The content hash covers normalized row values and provenance; inventory counts have a separate
hash and cannot substitute for dataset content. Any changed price or research row changes the
content hash and dataset version. Incomplete/rejected packages stay `RESEARCH_RAW_DATA`; only a
passing package enters `RESEARCH_CERTIFIED_DATA`.

## Provider capability audit

| Adapter present | Automatically usable | Research fields actually supported |
| --- | --- | --- |
| Yahoo/yfinance | Yes, live | Prices; corporate actions partial; no historical membership, delistings, identifier history, or total-return vintages |
| Stooq | Best effort | Daily prices only |
| Twelve Data | Only with optional key | Recent daily-price validation only |
| Alpha Vantage | Only with optional key | Recent daily-price validation only |
| exchange_calendars | Yes, local | XNYS sessions, holidays, opens/closes, and early closes |

Provider availability is not certification. The calendar rules can be generated automatically,
but the current local research package has no persisted calendar tied to matching historical
membership and lifecycle evidence.

## Fixture E2E and robustness

The complete small test fixture covers a permanent ID across `OLD -> NEW`, a delisted security,
historical membership intervals, PIT total-return vintages, symbol-change and delisting actions,
and four verified XNYS sessions. CSV, Parquet, and SQLite imports normalize to the same content
hash. It receives `CERTIFIED` only within `TEST_FIXTURE` scope and
`production_eligible=false`; strategy certification explicitly rejects that scope.

Full quality gates pass: Ruff, strict mypy over 357 project source files, and 608 pytest tests. A normal
no-refresh daily run also retained `DATA/PIT/FEATURE/FACTOR = PASS`, produced zero actionable
trades, and remained blocked by the genuine missing strategy approval and uninitialized
portfolio.

## Remaining blockers and next gate

1. `HISTORICAL_MEMBERSHIP_INCOMPLETE` and `CURRENT_CONSTITUENT_HISTORY_NOT_ALLOWED`.
2. `DELISTING_HISTORY_INCOMPLETE` and `SECURITY_IDENTIFIER_HISTORY_INCOMPLETE`.
3. `CORPORATE_ACTION_PIT_HISTORY_INCOMPLETE` and `PIT_TOTAL_RETURN_HISTORY_INCOMPLETE`.
4. `EXCHANGE_CALENDAR_INCOMPLETE` for a dataset-bound research package.

Formal Alpha research must remain closed until a licensed or user-supplied package passes these
contracts for the required strategy period. Locked OOS remains unopened and no Alpha parameter
was changed in this phase.
