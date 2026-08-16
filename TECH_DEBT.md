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

### TECH-ROUND24-001 — ROUND24 ETF sleeve models are research candidates

- Severity: OPEN (2026-08-14)
- Area: `instruments/`, `quant_engine/factors/etf_factors.py`,
  `quant_engine/portfolio/etf_sleeves.py`, `application/etf_sleeve_service.py`
- Description: ETF core/tactical sleeve models are labeled RESEARCH_CANDIDATE.
  They have no purged walk-forward / locked-OOS evidence and must not be
  claimed as certified alpha.  Promotion requires the ROUND24 E2 gate chain
  (PIT, purged walk-forward, embargo, locked OOS, cost, SPY/QQQ benchmark,
  stress).
- Remaining risk: None for the production path (Classical Champion
  unchanged); the risk is mislabeling these outputs as certified in future
  rounds.

### TECH-ROUND24-002 — ETF look-through unavailable

- Severity: OPEN (2026-08-14)
- Area: `quant_engine/portfolio/etf_sleeves.py` (OverlapReport)
- Description: ETF-stock overlap risk is computed via correlation clusters
  only.  Constituent holdings look-through data is not available, and the
  terminal reports `ETF look-through: UNAVAILABLE` rather than pretending
  to have constituent exposure.
- Remaining risk: A broad-market ETF plus concentrated stock sleeve can
  carry hidden single-name overlap; current mitigation is the correlation
  warning plus explicit UNAVAILABLE labeling.

### TECH-ROUND24-003 — Size neutralization degraded (no PIT market-cap source)

- Severity: OPEN (2026-08-14)
- Area: `quant_engine/input_assembler.py`, `quant_engine/risk/model.py`,
  `application/size_diagnostics.py`
- Description: Root-caused in ROUND24: the deterministic security master has
  no PIT market-cap provider, so size scores are empty and the risk model
  correctly reports SIZE_EXPOSURE_DEGRADED.  The warning is intentionally
  preserved (D11).  A PIT market-cap source (and backfilled cap history)
  would complete the neutralization diagnostics.
- Remaining risk: Size tilt is unmeasured for the operational path; the
  fail-closed label prevents pretending otherwise.

### TECH-ROUND24-004 — Regime v1 / drawdown governor research-only

- Severity: OPEN (2026-08-14)
- Area: `scenario_simulator/regime_engine_v1.py`,
  `quant_engine/risk/drawdown_governor.py`
- Description: Market Regime Engine V1 and the drawdown governor are
  RESEARCH_ONLY / RISK_OVERLAY_PROMOTION_CANDIDATE.  They never feed the
  production risk budget; production still shows REGIME_OPTIONAL_UNAVAILABLE.
  Promotion requires walk-forward/counterfactual evidence.
- Remaining risk: None for production today; future rounds must not
  hard-wire regime outputs into risk limits without evidence.

### TECH-ROUND24-005 — REAUTHORIZATION_REQUIRED after ROUND24

- Severity: OPEN (2026-08-14)
- Area: `var/operational/strategy_approval.json`,
  `var/operational/operational_policy.json`
- Description: ROUND24 changed the config/universe/code fingerprints, so the
  existing StrategyApproval (ALLOW_PROVISIONAL_FORWARD) and OperationalPolicy
  are identity-mismatched.  The operator must explicitly re-run
  `strategy-approval create` and `operational-policy create` after reviewing
  this round.  Nothing was auto-renewed.
- Remaining risk: Daily SIGNAL stays FAIL_BLOCKING until re-authorization.

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
