# Maintenance rules for AI agents

This file is binding guidance for Codex / DeepSeek / any AI maintainer.

## Quant core

- Do not redesign or silently change factor, alpha, probability, portfolio,
  risk, cost, benchmark, universe, or rebalance semantics.
- PIT correctness and fail-closed behavior are permanent invariants.
- Operational policy may only lower the historical research certification
  threshold; it can never bypass DATA, PIT, future-data, SIGNAL, PORTFOLIO,
  RISK, DECISION, or EXECUTION gates.
- Never auto-execute, never add a paper account, never let LLM select stocks or
  set probability/alpha/risk values.

## Reports and evidence

- Ordinary changes: Git commits only. Do not create new FINAL/CLOSURE/
  CHECKPOINT reports for routine work.
- Current truth: README.md, ARCHITECTURE.md, REPOSITORY_GUIDE.md, TECH_DEBT.md,
  and still-current specification docs.
- Audits: `docs/audits/YYYY-MM-DD_<topic>.md`.
- Superseded reports: `docs/history/YYYY-MM-DD-<phase>/` plus
  `docs/history/INDEX.md` entry.
- Automated run artifacts: `reports/` / `var/`, governed by
  `python main.py maintenance artifacts status` and
  `python main.py maintenance artifacts cleanup --dry-run|--commit`.

## Hygiene

- Never commit .env, keys, credentials, real holdings, runtime caches, or large
  datasets. Run `python scripts/secret_scan.py` before pushing.
- Keep migrations immutable; add a new revision instead of editing old ones.
- When in doubt about a file, retain it and record a TECH_DEBT entry.
