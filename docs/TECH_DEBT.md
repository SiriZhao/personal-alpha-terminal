# Personal Alpha Terminal — Technical Debt Register

## P0

### TECH-001 — Provisional operational approval changes production semantics

- Severity: P0
- Area: `terminal/cli.py` + `application/quant_daily_service.py` + `application/operational_readiness.py`
- Description: Uncommitted work auto-creates a `provisional-operational-*` approval on each
  daily run, which then classifies the run as `PROVISIONAL_ACTIONABLE` and can emit BUY/ADD
  recommendations without locked-OOS/full production certification. The artifact itself is
  immutable, hash-bound, and explicitly sets `full_research_certified=false` with
  `research_certification_state=NOT_CERTIFIABLE`, so it is not a forged full approval, but it
  does replace the earlier `NON_ACTIONABLE` behavior.
- Why retained: The work is uncommitted, covered by its own tests (727 total pass), and may be an
  intentional product decision from the prior session; removing or weakening it without user
  decision would itself change semantics.
- Risk: Users may mistake provisional actionability for certified production approval, or the
  strategy may trade before historical certification evidence exists.
- Recommended future action: Decide and record one of: (a) keep provisional mode but require
  explicit user opt-in and make terminal wording unmistakably provisional; (b) gate it behind a
  strict data/cost/risk evidence set; or (c) remove the auto-approval while retaining research
  provider/EDGAR code.

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
