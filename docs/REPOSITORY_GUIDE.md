# Personal Alpha Terminal — Repository Guide

This guide is for maintainers (human or AI) who open this repository. Its goal is to prevent a
second implementation from being created because the current structure is unclear.

## Top-level layout

```text
main.py                         Formal terminal entry (delegates to terminal CLI)
run_terminal.bat                Windows launcher (uses .venv, never auto-submits orders)
pyproject.toml                  Packaging, dependencies, ruff/mypy/pytest settings
config.yaml / config.example.yaml
                                Runtime config (no holdings, no secrets)
.env.example / .env.production.example
                                Environment variable templates (secrets never committed)
src/personal_alpha_terminal/    Production package
tests/                          Test suite
scripts/                        Operational/research scripts and secret scanner
migrations/                     Alembic schema history (immutable once committed)
docs/                           Current + historical documentation
artifacts/latest/               Small machine-readable certification snapshots
config/                         Extra research contracts (SEC EDGAR source contract)
data/                           Local market/research data (git-ignored except contracts)
var/                            Runtime database, logs, caches (git-ignored)
reports/                        Daily-run/research evidence snapshots (git-ignored)
packaging/                      Release/PyInstaller tooling
```

## Source package map

```text
src/personal_alpha_terminal/
  terminal/cli.py               THE formal user CLI (daily, portfolio, research-data, review)
  console.py                    Installed `pat` entry point wrapper
  application/                  Orchestrators and services (daily run, intelligence, operational)
  quant_engine/                 Deterministic quant core: factors, alpha, portfolio, risk, decisions
  data/                         Market data, PIT, universe, calendar, database access
  intelligence/                 LLM/event/research layer (DeepSeek via provider abstraction)
  agents/                       LLM provider boundary and research agent
  portfolio/                    Manual ledger and portfolio management
  models/                       SQLAlchemy ORM models
  core/                         Config, logging, fingerprints, retention, runtime bootstrap
  alpha_discovery/, backtest/, research/, strategies/, scenario_simulator/, analysis/,
  decision_engine/, validation/, reports/, automation/, us_quant/
                                Specialized research/strategy sub-packages
  scripts/                      Legacy research CLI scripts (kept; see TECH_DEBT)
```

## Do not casually modify

- `migrations/` — revisions are immutable once committed; use a new revision.
- `src/personal_alpha_terminal/quant_engine/` — deterministic quant semantics.
- `src/personal_alpha_terminal/data/` — PIT/corporate-action/cache semantics.
- `src/personal_alpha_terminal/portfolio/` — real ledger semantics.
- `config.yaml`, `.env*` — local user configuration.
- `data/`, `var/`, `reports/` — runtime data and evidence.

## Entry points

- Terminal: `python main.py` (or `pat` after install).
- Daily run without provider refresh: `python main.py --no-refresh daily`.
- Research data CLI: `python main.py research-data --help`.
- Tests: `python -m pytest` (run from repo root so `tests`/`scripts` import correctly).
- Secret scan: `python scripts/secret_scan.py`.

## Principles

- One formal daily pipeline; UI only renders `DailyQuantResult`.
- Fail closed: missing/uncertified input blocks recommendations; no mock fallback in production.
- No auto execution; Charles Schwab/other brokers are manual only.
- LLM is a structured intelligence/research layer; it never replaces deterministic factors,
  probability, portfolio, or risk logic, and is gated to SHADOW until certified.

## Report lifecycle (mandatory)

- Ordinary changes are recorded by Git commits only. Do not create new
  `*_FINAL`, `*_CLOSURE`, `*_CHECKPOINT`, `*_REPORT` files for routine work.
- Current truth lives only in `README.md`, `ARCHITECTURE.md`,
  `REPOSITORY_GUIDE.md`, `TECH_DEBT.md` and genuinely current specification docs.
- Audits go to `docs/audits/YYYY-MM-DD_<topic>.md`.
- Superseded session reports go to `docs/history/YYYY-MM-DD-<phase>/` and are
  registered in `docs/history/INDEX.md`.
- Automated run artifacts never enter `docs/`; they stay in the runtime
  `reports/` / `var/` evidence system and are governed by `maintenance artifacts`.
