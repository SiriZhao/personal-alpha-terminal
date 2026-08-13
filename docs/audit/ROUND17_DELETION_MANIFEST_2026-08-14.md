# ROUND17 Deletion Manifest

Date: 2026-08-14

## Policy

Only regenerable caches and clearly temporary debug directories are deleted.
No protected runtime, database, ledger, SEC/PIT evidence, calibration,
promotion-candidate, release, or source path is deleted.

If a target is uncertain, it is retained. Archive is preferred over deletion
for uncertain historical content.

## Deletion list

| Target | Type | Reason | Decision |
|---|---:|---|---|
| **/__pycache__ | cache | Python bytecode | DELETE |
| .mypy_cache/ | cache | mypy cache | DELETE |
| .pytest-tmp/ | cache | pytest basetemp | DELETE |
| .pytest_cache/ | cache | pytest cache | DELETE |
| .ruff_cache/ | cache | ruff cache | DELETE |
| .tmp/ | temp | debug/probe artifacts | DELETE |
| .codex-temp/ | temp | debug/probe artifacts | DELETE |

## Protected no-delete list

- var/personal_alpha.db
- var/forward-ledger.jsonl
- var/shadow-ledger.jsonl
- var/operational/
- var/intelligence/
- var/research-data/
- var/backups/
- reports/validation-artifacts/
- artifacts/
- docs/audit/
- config.yaml
- src/, tests/, migrations/, scripts/, packaging/

## Verification

- Deletion is performed with PowerShell Remove-Item after path containment checks.
- Git tracked worktree must remain clean before and after deletion.
- Full pytest, ruff, mypy, secret scan, doctor, daily smoke, intelligence status,
  and portfolio/database integrity must pass after cleanup.