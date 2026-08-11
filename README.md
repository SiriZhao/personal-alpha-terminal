# Personal Alpha Terminal

Personal, medium/low-frequency, long-only U.S. equity decision support. It runs daily, produces a manual action list or HOLD, and never places an order. Charles Schwab execution is manual. This is not investment advice.

## Architecture and safety boundary

The deterministic chain is `DATA -> PIT -> FEATURE -> FACTOR -> CANDIDATE -> APPROVED SIGNAL -> PORTFOLIO -> RISK -> DECISION -> MANUAL EXECUTION`. A candidate is research output; a signal has passed signal validity; an approved signal also has an immutable production certification; only a risk-approved decision can become a proposed manual trade.

The system fails closed on future rows, stale/incomplete data, missing PIT or survivorship evidence, missing strategy approval, an unselected portfolio, or risk failure. No stage is renamed or bypassed to produce a trade. Optional probability and market-regime overlays may be `UNCALIBRATED` / `OPTIONAL_UNAVAILABLE`; they do not change deterministic alpha. LLM use is optional and explanation-only—never stock selection, alpha, sizing, risk, or execution.

## Data and PIT

Yahoo Finance is the default daily provider. Twelve Data, Alpha Vantage, and Stooq are optional adapters subject to the same certification. Each run records cutoff, snapshot/version ID, provider, counts, coverage, quality status, certification state, and content hash. Features and SPY/QQQ benchmarks use the same completed-session PIT convention. Free current-universe data is not accepted as historical survivorship-safe evidence.

## Portfolio initialization

Holdings are never inferred. Create a persistent, auditable manual ledger (cash-only is valid):

```powershell
python main.py portfolio-init --name "My Portfolio" --cash 100000
python main.py portfolio-init --name "My Portfolio" --cash 50000 --position "AAPL=10:180" --position "MSFT=5"
python main.py portfolio-list
```

Then verify the returned ID and set it explicitly in local `config.yaml`:

```yaml
portfolio_id: 1
```

An existing but unselected ledger remains `PORTFOLIO_NOT_SELECTED`; zero ledgers is `PORTFOLIO_NOT_INITIALIZED`. A Schwab CSV can be previewed and then committed explicitly:

```powershell
python main.py portfolio-import schwab.csv --portfolio-id 1 --as-of 2026-08-11
python main.py portfolio-import schwab.csv --portfolio-id 1 --as-of 2026-08-11 --commit --cash 25000
```

## Daily workflow

```powershell
python main.py daily
python main.py data-provider status
python main.py doctor
```

Read the top-level `ACTIONABLE` / `NON_ACTIONABLE` classification and primary blockers first. Evidence is stored under the configured `reports/daily-runs/<run_id>/` as a result snapshot and run certificate with canonical input/result hashes. Runtime reports, databases, caches, `.env`, credentials, and real portfolio data are ignored by Git.

Strategy production approval requires chronological train/validation/locked-OOS or walk-forward evidence, identical PIT convention for SPY and QQQ, survivorship and corporate-action controls, commissions/spread/slippage/impact, and acceptable turnover, drawdown, concentration, benchmark alpha, and stability. `quant_engine.strategy_certification` evaluates and hashes that evidence; insufficient data produces `NOT_CERTIFIABLE`, failed alpha/risk gates produce `REJECTED`, and neither can create an approval artifact.

Historical research uses provider-neutral contracts in `quant_engine.research_data`
and `quant_engine.research_dataset`. The domains are explicit:

- `LIVE_DAILY_DATA`: today's analysis inputs; never historical backtest evidence.
- `RESEARCH_RAW_DATA`: imported rows that are normalized and audited but not approved.
- `RESEARCH_CERTIFIED_DATA`: rows whose membership, identity, lifecycle, corporate-action,
  total-return, calendar, provenance, period coverage, and content hash all pass.

The current ticker list is never backfilled into history. A final adjusted series downloaded
today is not a PIT total-return vintage. ETF, equity, and benchmark memberships use separate
`US_ETF`, `US_EQUITY`, and `BENCHMARK` classifications.

Research ingest is separate from `daily` and never runs automatically:

```powershell
python main.py research-data audit
python main.py research-data --root var/research-data status
python main.py research-data --root var/research-data import data/research/imports/package.csv --required-start 2015-01-02 --required-end 2026-06-30
python main.py research-data --root var/research-data certify
python main.py research-data --root var/research-data manifest
```

`import` accepts long-form CSV or Parquet and SQLite. Every row carries the common fields
`dataset_id`, `schema_version`, `dataset_provider`, `dataset_source`, `retrieved_at`,
`as_of`, `cutoff`, `use_scope`, `record_type`, `source`, and `provider`. Record types are:

- `SECURITY`: permanent ID, ticker validity, exchange, listing/delisting, security type.
- `MEMBERSHIP`: universe ID/type, effective interval, availability and source timestamp.
- `PRICE`: raw OHLCV plus explicit adjustment kind and optional PIT total-return vintage.
- `CORPORATE_ACTION`: effective/announcement/available dates and supplied lifecycle terms.
- `CALENDAR`: calendar ID, session, open/close, and early-close flag.

SQLite may use one `research_rows` table or the named tables `securities`, `memberships`,
`prices`, `corporate_actions`, and `calendar_sessions`. Parquet support is in the `research`
dependency group. Unknown fields remain unknown; an unavailable delisting return is never
zero. `TEST_FIXTURE` packages can prove plumbing but always have `production_eligible=false`.
Exit code 3 with `NOT_CERTIFIABLE` is expected when critical evidence is absent. Large raw,
normalized, and certified research rows stay under ignored `data/research/` or `var/`; only
source, schemas, small fixtures, tests, and concise non-private reports belong in Git.

## Configuration

Copy `config.example.yaml` and `.env.example`; keep secrets only in the environment or local untracked files. Optional provider keys are `TWELVE_DATA_API_KEY` and `ALPHA_VANTAGE_API_KEY`. See [LLM configuration](docs/LLM_CONFIGURATION.md), [architecture](docs/ARCHITECTURE.md), [terminal guide](docs/TERMINAL_GUIDE.md), and [production closure report](docs/PRODUCTION_CLOSURE_REPORT.md).

## Development and tests

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest -q
```

Fixture approval artifacts prove plumbing only; they are not real investment evidence. Historical results do not guarantee future performance.
