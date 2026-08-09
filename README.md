# Personal Alpha Terminal

Terminal-first personal quantitative decision system for medium/low-frequency U.S. equity portfolio management.

The deterministic Quant Pipeline performs data checks, point-in-time validation, factor and alpha calculation, portfolio construction, risk control, and execution planning. Charles Schwab is supported only as a CSV/manual-execution workflow. There is no broker API and no automatic trading. LLM support is optional and explanation-only.

## What it does

- Runs one audited chain: Data → PIT → Features → Factors → Alpha → Probability → Portfolio → Risk → Decision → Execution Plan.
- Fails closed when data, PIT evidence, a real portfolio, model approval, or risk checks are insufficient.
- Imports a Charles Schwab holdings CSV without modifying the source file.
- Records ACCEPT/REJECT/WATCH and user-entered fills; ACCEPT never changes holdings.
- Keeps immutable daily run snapshots so a result can be reproduced and reviewed.
- Provides PIT-gated historical backtests. Fixture tests never count as real-data alpha evidence.

## Quick start

Double-click `PersonalAlphaTerminal.exe`. With no real portfolio, the terminal reports `PORTFOLIO NOT INITIALIZED` and does not create buy orders.

```text
PersonalAlphaTerminal.exe portfolio-init --name "My Portfolio" --cash 100000
PersonalAlphaTerminal.exe portfolio-import schwab.csv --portfolio-id 1 --as-of 2026-08-08
PersonalAlphaTerminal.exe portfolio-import schwab.csv --portfolio-id 1 --as-of 2026-08-08 --commit
PersonalAlphaTerminal.exe daily
```

The first import command is preview-only. `--commit` is required to update the real ledger.

## Daily workflow

1. Run `daily` (the double-click default).
2. Read DATA HEALTH and every PIPELINE gate.
3. Treat candidates and signals as diagnostic evidence, not trades.
4. Only `FINAL VALIDATED DECISIONS` are formal outputs.
5. Use `accept`, `reject`, or `watch` to record your review.
6. Place any accepted order manually at Charles Schwab.
7. After each broker fill, use `mark-executed` with a unique fill ID. Partial fills update only
   the quantity actually filled; restart-safe order state remains `PARTIAL` until complete.

```text
PersonalAlphaTerminal.exe accept <recommendation_id> --run-id <run_id>
PersonalAlphaTerminal.exe mark-executed <recommendation_id> --run-id <run_id> --fill-id <fill_id> --price 100 --quantity 10 --fees 0
```

`cancel-execution` and `modify-execution` require the same run/recommendation identity and an
audit reason. They never contact Charles Schwab. Only a user-entered fill changes cash or shares.

## Commands

`daily`, `refresh`, `data`, `portfolio`, `portfolio-init`, `portfolio-import`, `factors`,
`probability`, `risk`, `decisions`, `backtest`, `research`, `doctor`, `diagnostics`, `settings`,
`accept`, `reject`, `watch`, `mark-executed`, `cancel-execution`, `modify-execution`, `version`,
`help`.

`NO_ACTION` means every required stage completed and no rebalance survived the no-trade rules.
`BLOCKED`/`NOT_ACTIONABLE` means evidence is incomplete; read the blocking stage, reason, cutoff,
run ID and configuration/model/data hashes. It is the expected safe result when validation is
not yet sufficient.

## Data, logs, and backup

User data is stored separately from the program:

```text
%LOCALAPPDATA%\PersonalAlphaTerminal
```

Back up `data/`, `config.yaml`, `config.env`, and `backups/`. Do not share API keys. Logs are rotated (`app.log`, `data.log`, `error.log`); generated reports and diagnostics have bounded retention. Databases, portfolio records, configurations, and immutable data snapshots are never removed by retention cleanup.

## Documentation

- [Terminal guide](docs/TERMINAL_GUIDE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [LLM configuration](docs/LLM_CONFIGURATION.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## Source verification

Python 3.12–3.14 is supported for development. End users of the Windows release do not install Python or Node.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

## Risk disclaimer

This software is research and decision support, not investment advice. Historical results do not guarantee future performance. Free market-data sources cannot certify complete historical constituent, delisting, corporate-action, or fundamental-restatement history; the affected actions and backtests remain blocked. Prefer `NO ACTIONABLE DECISION` over an incomplete evidence chain.
