# ROUND52 Baseline, Test, and Evidence Integrity

- Date: 2026-08-17
- ROUND52 baseline SHA: `2d3172edf0db02ab8152ce1e606cd7e1a493a3b6`
- Declared ROUND42-51 implementation SHA: `fa3c962b9bf9d6429daab0684114a526ca4a7230`
- Relationship: `fa3c962` is an ancestor of the retained ROUND52 baseline.
- Working tree at pre-flight: clean.

## Post-closure reconciliation

Commit `2d3172e` retained the ROUND42-51 source implementation and removed
obsolete generated/history material. It also changed one unit-test assertion
from 26 to 66 canonical probability rows because the test read the mutable
workspace forward ledger. ROUND52 removes that runtime-data dependency by
injecting deterministic audit and evaluation documents.

## Python 3.14 / pytest ACL diagnosis

Pytest's built-in Windows temp-directory plugin created mode-0700 numbered
directories that the managed process could not subsequently enumerate. The
suite now disables that plugin and uses a unique, repository-local, ignored
temp root per pytest process. Test directories are not recursively deleted
while SQLite, logging, or backup handles may still be open.

## Validation

- Full pytest: PASS, `1279 passed`, one SQLAlchemy deprecation warning.
- Quant-critical: PASS, `6 passed`.
- ROUND30 deterministic promotion-report tests: PASS, `7 passed`.
- Ruff: PASS.
- Mypy strict: PASS, `491 source files`.
- Secret scan: `SECRET_SCAN_PASS`.

`ROUND52_VERDICT = PASS`

No Quant, alpha, probability, portfolio, risk, cost, benchmark, universe, or
execution business semantics changed in ROUND52.
