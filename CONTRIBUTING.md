# Contributing

## Project contract

This repository is a personal quantitative terminal with strict safety rules.

Do not change without evidence:

- factor definitions;
- Alpha semantics;
- Probability production influence;
- portfolio construction;
- risk formulas;
- transaction cost assumptions;
- PIT and future-leakage rules;
- OperationalPolicy governance;
- execution semantics.

LLM/DeepSeek features must remain SHADOW until a locked-OOS, after-cost,
calibrated, survivorship-safe approval artifact exists.

## Development environment

Use `.venv314`:

```powershell
.\.venv314\Scripts\python.exe -m pip install -e ".[dev,ai]"
```

## Required checks

Before commit:

```powershell
.\.venv314\Scripts\ruff.exe check .
.\.venv314\Scripts\python.exe -m mypy src\personal_alpha_terminal
.\.venv314\Scripts\python.exe scripts\secret_scan.py
.\.venv314\Scripts\python.exe -m pytest -q --basetemp=.tmp\pytest-basetemp
```

Use repository-local basetemp on Windows when the system pytest temp directory
is ACL-blocked.

## Coding rules

- Source and docs are UTF-8.
- Do not write secrets into tracked files.
- Do not create paper accounts or simulated fills in the real ledger.
- Do not auto-execute orders.
- Do not delete runtime data, ledgers, SEC/PIT evidence, calibration artifacts,
  or OperationalPolicy artifacts without an explicit manifest.
- Keep quant and UI changes separately reviewable.
- Commit locally; do not push unless explicitly authorized.

## Cleanup policy

Before any deletion, create a deletion manifest. If uncertain, archive instead
of deleting. Never delete current database, ledgers, SEC raw evidence, PIT
evidence, calibration artifacts, promotion candidates, or current release
docs.