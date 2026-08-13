# Repository Storage Inventory

Date: 2026-08-14

## Snapshot

- Total files before cleanup: 89,346
- Total size before cleanup: 3,526.66 MB (3.44 GB)
- Git object size: 2.05 MiB pack
- Tracked files: 832
- Tracked size: 5.59 MB
- Worktree: clean before cleanup

## Categories

| Category | Path | Files | Size MB | Tracked | Runtime | Safe delete | Should archive | Should gitignore |
|---|---|---:|---:|---|---|---|---|---|
| SOURCE | src/ | 1213 | 12.05 | Yes | No | No | No | No |
| TEST | tests/ | 736 | 12.35 | Yes | No | No | No | No |
| DOCS | docs/ | 222 | 1.10 | Yes | No | No | Milestones only | No |
| CONFIG | config/ + root configs | 4 | 0.01 | Yes | No | No | No | No |
| RUNTIME | var/ | 1075 | 1054.11 | No | Yes | No | No | Yes |
| DATABASE | var/personal_alpha.db | 1 | 989.09 | No | Yes | No | No | Yes |
| CACHE | .mypy_cache/ | 3 | 59.91 | No | Yes | Yes | No | Yes |
| CACHE | .pytest-tmp/ | 5200 | 55.88 | No | Yes | Yes | No | Yes |
| CACHE | .pytest_cache/ | 6 | 0.10 | No | Yes | Yes | No | Yes |
| CACHE | .ruff_cache/ | 44 | 0.09 | No | Yes | Yes | No | Yes |
| CACHE | data/cache/ | 10 | 30.35 | No | Yes | No | No | Yes |
| REPORTS | reports/ | 1300 | 233.83 | No | Yes | Retention-managed | No | Yes |
| AUDIT | docs/audit/ | many | tracked | Yes | No | No | Key milestones | No |
| BUILD | packaging/ | 4 | 0.01 | Yes | No | No | No | No |
| TEMP | .tmp/ | 1876 | 19.88 | No | Yes | Yes | No | Yes |
| TEMP | .codex-temp/ | 440 | 7.50 | No | Yes | Yes | No | Yes |
| ENV | .venv/ | 36874 | 1140.08 | No | Yes | No | No | Yes |
| ENV | .venv314/ | 39689 | 894.86 | No | Yes | No | No | Yes |
| LEGACY | var/backups/ | 710 | 6.80 | No | Yes | No | Yes | Yes |
| RUNTIME | var/intelligence/ | 231 | 22.16 | No | Yes | No | No | Yes |
| RUNTIME | var/research-data/ | 105 | 35.66 | No | Yes | No | No | Yes |

## Protected paths

- src/, tests/, migrations/, scripts/, packaging/
- config.yaml, .env.example, .gitignore, pyproject.toml
- var/personal_alpha.db
- var/forward-ledger.jsonl, var/shadow-ledger.jsonl
- var/operational/
- var/intelligence/ raw SEC/PIT/LLM evidence
- var/research-data/
- artifacts/
- reports/validation-artifacts/
- docs/audit/ key milestone reports
- docs/USER_GUIDE_zh-CN.md and current docs

## Cleanup candidates

- __pycache__ directories: regenerable
- .mypy_cache/: regenerable
- .pytest-tmp/: regenerable
- .pytest_cache/: regenerable
- .ruff_cache/: regenerable
- .tmp/: temporary debug/probe files
- .codex-temp/: debug artifacts and temporary probes

No runtime, database, ledger, SEC/PIT, calibration, promotion-candidate, or current release asset is a cleanup candidate.

## After cleanup

- Total files after cleanup: 80,397
- Total size after cleanup: 3,373.27 MB (3.29 GB)
- Workspace reduction: 153.39 MB
- Git tracked size: unchanged at 5.59 MB
- Removed: Python __pycache__, .mypy_cache, .pytest-tmp, .pytest_cache, .ruff_cache, .tmp, .codex-temp

Protected runtime remains intact: var/personal_alpha.db, var/intelligence, var/research-data, var/backups, reports, artifacts.