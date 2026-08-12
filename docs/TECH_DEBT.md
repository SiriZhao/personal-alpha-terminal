# Personal Alpha Terminal — Technical Debt Register

## P0

### TECH-001 — Provisional operational approval changes production semantics

- Severity: RESOLVED (2026-08-12)
- Area: `terminal/cli.py` + `application/quant_daily_service.py` + `application/operational_readiness.py`
- Description: Resolved by binding provisional operational advice to an explicit, persistent
  `OperationalPolicy` (`operational-policy set`), removing the daily-run auto-issuing hook, and
  hardening the pipeline so provisional signals cannot become production-approved without an
  explicit policy. Data/PIT/signal/risk gates remain absolute.
- Remaining risk: An operator who explicitly issues `ALLOW_PROVISIONAL` accepts degraded
  recommendations; the terminal always labels them as provisional and non-research-certified.

## P1

### TECH-002 — Untracked root-level reports are not governed

- Severity: P1
- Area: `docs/*.md` (27 untracked files)
- Description: Multiple uncommitted report docs with strong names (`*_FINAL`, `*_CERTIFICATION`,
  `*_PRODUCTION_*`) sit at `docs/` root.
- Why retained: They belong to the uncommitted feature set and may be referenced by its scripts.
- Risk: Stale/overstated claims can be mistaken for current truth.
- Recommended future action: Review claims against gates, then commit or move under
  `docs/history/` with an index.

### TECH-003 — Git-ignored runtime evidence growth

- Severity: P1
- Area: `reports/`, `var/`
- Description: Runtime snapshots/logs/db accumulate locally (tens of MB).
- Why retained: Evidence chain and ledger are intentionally kept locally.
- Risk: Disk growth; no data-loss risk.
- Recommended future action: Periodic retention policy review using `core.retention`.

## P2

### TECH-004 — Legacy root CLI package

- Severity: P2
- Area: `src/personal_alpha_terminal/cli.py`, `src/personal_alpha_terminal/scripts/daily_pipeline.py`
- Description: Non-entry-point CLI retained; only in-tree caller is the scripts wrapper.
- Why retained: Packaged code without a verified removal contract.
- Risk: Confusion / duplicate entry points.
- Recommended future action: Verify no docs/installer references, then delete both files.

### TECH-005 — Legacy research scripts package

- Severity: P2
- Area: `src/personal_alpha_terminal/scripts/*`
- Description: Research scripts duplicated by root `scripts/` and terminal CLI.
- Why retained: Two modules have tests; no removal contract.
- Risk: Maintenance duplication.
- Recommended future action: Dedicated cleanup round with import/ref map.

### TECH-006 — Duplicate module names across packages

- Severity: P2
- Area: `models/event_study.py` vs `intelligence/event_study.py`; `alpha_discovery/walk_forward.py`
  vs `backtest/walk_forward.py`; `models/portfolio_risk.py` vs `quant_engine/risk/portfolio_risk.py`
- Description: Same feature name in different packages; reference counts show active paths.
- Why retained: No safe merge verified.
- Risk: Import confusion.
- Recommended future action: Document canonical module per feature; merge only with tests.

### TECH-007 — Dual local virtual environments

- Severity: P2
- Area: `.venv` (~1.1 GB), `.venv314` (~0.9 GB)
- Description: Two local envs both git-ignored.
- Why retained: Environment migration is outside audit scope and may be intentional.
- Risk: Disk usage and version drift.
- Recommended future action: Pick one canonical env; keep the other only if a Python-version
  matrix is required.

## P3

- No pure-cosmetic items tracked this round.
