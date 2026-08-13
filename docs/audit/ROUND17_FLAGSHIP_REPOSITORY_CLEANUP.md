# ROUND17 - Flagship Repository Cleanup

Date: 2026-08-14

Verdict: `ROUND17_READY`

## Summary

ROUND17 produced a full storage inventory, created a deletion manifest, removed
only regenerable caches and clearly temporary debug directories, and added
flagship repository documentation. No runtime, database, ledger, SEC/PIT,
calibration, promotion-candidate, current release, or source asset was
deleted.

## Inventory

Full inventory: [REPOSITORY_STORAGE_INVENTORY.md](REPOSITORY_STORAGE_INVENTORY.md)

- Total files before cleanup: 89,346
- Total size before cleanup: 3,526.66 MB (3.44 GB)
- Tracked files: 832
- Tracked size: 5.59 MB
- Git pack size: 2.05 MiB
- Total files after cleanup: 80,397
- Total size after cleanup: 3,373.27 MB (3.29 GB)
- Workspace reduction: 153.39 MB

## Deletion manifest

Manifest: [ROUND17_DELETION_MANIFEST_2026-08-14.md](ROUND17_DELETION_MANIFEST_2026-08-14.md)

Removed:

- Python __pycache__ directories
- .mypy_cache/
- .pytest-tmp/
- .pytest_cache/
- .ruff_cache/
- .tmp/
- .codex-temp/

Protected and retained:

- var/personal_alpha.db (current database)
- var/forward-ledger.jsonl and var/shadow-ledger.jsonl
- var/operational/ OperationalPolicy artifacts
- var/intelligence/ raw SEC/PIT/LLM evidence
- var/research-data/
- var/backups/
- reports/validation-artifacts/
- artifacts/
- docs/audit/ milestone reports
- config.yaml and all source/test/migration files

## Flagship files

- README.md: updated with Chinese README link and manual-decision positioning.
- README.zh-CN.md: created.
- CHANGELOG.md: updated with ROUND14-17 status.
- SECURITY.md: created.
- CONTRIBUTING.md: created.
- ARCHITECTURE.md: already present and retained.

## Gates

- Full pytest: 963 passed
- quant_critical: 31 passed
- Ruff: All checks passed
- Strict mypy: 420 source files, no issues
- Secret scan: SECRET_SCAN_PASS
- doctor: PASS; database, migration, portfolio, intelligence corpus verified
- intelligence status: 44 raw / 44 PIT / 44 issuer / 24 mapped / 18 events
- portfolio ledger: portfolio_id=main, cash=100000.0
- daily --no-refresh smoke: UTF-8 decode OK, overview and action list rendered

## Safety

No OperationalPolicy was created or renewed. No automatic execution was
enabled. No ledger, database, SEC/PIT evidence, calibration artifact, or
current release asset was deleted.

## Final disposition

`ROUND17_READY`

ROUND18 scope is not defined in this prompt, so no further autonomous round
was started.