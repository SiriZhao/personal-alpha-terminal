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

- Severity: RESOLVED (2026-08-12)
- Area: `docs/*.md` (27 untracked files)
- Description: Resolved by archiving session reports under
  `docs/history/2026-08-12-session/`, creating `docs/history/INDEX.md`, and adding
  a mandatory report lifecycle to `AGENTS.md`, `README.md`, and
  `REPOSITORY_GUIDE.md`: ordinary changes use Git commits; only major audits get
  `docs/audits/YYYY-MM-DD_<topic>.md` reports.
- Remaining risk: Discipline depends on maintainers following AGENTS.md; no code
  can enforce documentation habits.

### TECH-003 — Git-ignored runtime evidence growth

- Severity: RESOLVED (2026-08-12)
- Area: `reports/`, `var/`
- Description: Resolved by adding a declarative `RuntimeArtifactPolicy` in
  `core/retention.py` plus `maintenance artifacts status` and
  `maintenance artifacts cleanup --dry-run|--commit`. Daily reproducibility
  evidence is retained 180 days, diagnostics 30 days, and CRITICAL areas (ledger,
  policy, research truth source, validation artifacts, backups, certification
  snapshots) are never auto-pruned. Cleanup is dry-run by default.
- Remaining risk: Operators may still choose `--commit` on a daily area; policy is
  documented and test-protected, but no automatic hard bound is enforced on disk.

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

- Severity: P2 / IN PROGRESS (2026-08-14)
- Area: `.venv`, `.venv314`
- Description: Current execution paths and long-term documentation use the existing Python
  3.12 `.venv`; `.venv314` has no active source/config dependency but remains on disk pending
  a safe local filesystem cleanup while the terminal instance is active.
- Remaining risk: Disk usage and version drift remain until the obsolete environment is removed.
- Next action: Stop the active terminal instance, re-verify the path, then remove `.venv314`
  with the approved workspace cleanup mechanism.

## P3

- No pure-cosmetic items tracked this round.
