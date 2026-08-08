# Quant Core Closure Part 1 — Immutable Baseline

Captured: 2026-08-08 (Asia/Shanghai)

## Repository boundary

- Project root: `E:\CSDIY\Vibe Coding Project\personal-alpha-terminal`
- Pre-baseline project Git state: no independent `.git` directory.
- Parent repository state: zero commits and unrelated content; it is not a valid project history.
- Dedicated repository branch: `codex/quant-core-closure-part1`.
- Initial production-source manifest: `PRODUCTION_SOURCE_SHA256.txt` (554 files).

## Runtime and dependencies

- Validation interpreter: CPython 3.12.10, 64-bit.
- Secondary installed interpreter: CPython 3.14.
- Supported range from `pyproject.toml`: `>=3.12,<3.15`.
- Dependency contract: `pyproject.toml`; the system Python had no project validation
  dependencies installed at capture time. An ignored project virtual environment is used for
  subsequent validation.

## Schema and databases

- Alembic source head at capture: `b8a2d6f4c901`.
- Development DB: `E:\CSDIY\Vibe Coding Project\personal-alpha-terminal\var\personal_alpha.db`
  - SHA256: `ab40b600b4cfef8cc7ebe3e052adaa4d906f8acdd1442f6f4c9577f8e8d4a0f2`
  - revision: `b8a2d6f4c901`
  - tables: 84
  - security master rows: 0
  - corporate-action rows: 0
- Desktop DB: `%LOCALAPPDATA%\PersonalAlphaTerminal\data\personal_alpha.db`
  - SHA256: `f3012e3ef83338af1b61cbb92ccacc2135d2970d045aaec4328d868f66c75c3a`
  - revision: `b8a2d6f4c901`
  - tables: 95
  - security master rows: 18
  - corporate-action rows: 0

## Baseline risk finding

Both development and desktop databases existed with materially different schemas and content.
This is a confirmed runtime split-brain risk. No merge or implicit fallback was performed.

