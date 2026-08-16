# Worktree Reconciliation and TECH-001 Closure — 2026-08-12

## 1. Original 87 uncommitted files — final classification

Baseline: 35 modified + 52 untracked (87 files) on top of `02bf222`.

| Category | Count | Files |
|---|---:|---|
| A. production feature (committed) | 21 | research provider/SEC modules, operational policy, daily/provisional wiring |
| B. tests (committed) | 14 | research provider tests, policy hardening tests, provisional mode tests, modified regression tests |
| C. config (committed) | 2 | `config/research/*` |
| D. documentation (committed) | 7 | 3 current guides kept at `docs/`, 3 modified AI-native docs, TECH_DEBT update |
| E. historical report (archived) | 24 | session reports moved under `docs/history/2026-08-12-session/` |
| F. generated/cache (cleaned) | 0 | no generated/cache files remained in the 87 |
| G. experimental (committed) | 0 | research modules are committed as feature code |
| H. duplicate (kept, recorded) | 0 | no new duplicates found |
| I. dead (none removed) | 0 | nothing proven dead |
| J. unknown (retained) | 0 | none |

Artifacts: 6 committed as research evidence, 2 superseded provisional artifacts archived.

## 2. Committed files

All production/test/config source and current docs were committed. See section 12 for
the commit list.

## 3. Deleted files

No source, test, config, migration, or data file was deleted. The only removal was a
test-issued `var/operational/operational_policy.json` (issued_by `USER:test:e2e`) that
was written by the e2e provisional test before its policy path was isolated.

## 4. Archived files

- 24 dated session reports → `docs/history/2026-08-12-session/` with `INDEX.md`.
- `artifacts/latest/provisional_daily_run.json` and
  `artifacts/latest/sec_round_2_5b_real_pilot_certification.json` (superseded by
  TECH-001 hardening) → `docs/history/2026-08-12-session/artifacts/`.

## 5. Files still retained

- `scripts/run_provisional_daily_run.py` was retained but refactored to require an
  explicit operational policy instead of auto-issuing an approval.
- All committed research/SEC/provider code remains active.

## 6. TECH-001 original problem

`terminal/cli.py::_ensure_provisional_operational_approval()` auto-created a
`provisional-operational-*` approval on every daily run, and the pipeline consumed that
approval to classify the run as `PROVISIONAL_ACTIONABLE` with real BUY/ADD
recommendations — even though `full_research_certified=false` and
`research_certification_state=NOT_CERTIFIABLE`. The daily run was effectively
self-issuing its own trading permission.

## 7. New Operational Policy design

`application/operational_readiness.py` now defines:

- `OperationalPolicyDecision`: `ALLOW_PROVISIONAL` | `BLOCK`.
- `OperationalPolicy`: persistent, hash-bound policy bound to an exact
  `OperationalApprovalIdentity` (strategy version, factor/universe/portfolio/risk/cost
  hashes), with `issued_by`, `created_at`, `reason`, optional `expires_at`, and
  `artifact_hash`.
- `OperationalPolicyStore`: read-only daily accessor; missing/invalid policy fails
  closed. Writes only via explicit CLI.
- `classify_operational_state()` and `build_operational_identity()` shared helpers.

CLI:

```text
python main.py operational-policy show
python main.py operational-policy set --decision ALLOW_PROVISIONAL --reason "..."
```

`run_daily` no longer calls any approval-producing hook. Re-running daily never creates
policy/approval files.

## 8. Research Certification vs Operational Permission separation

- Research certification remains a separate truth: current state is `NOT_CERTIFIABLE`
  and is never rewritten.
- Operational permission only answers: given the bound identity and current research
  state, may the pipeline emit provisional advice?
- `DailyQuantResult` carries `operational_policy_id`, `operational_policy_decision`,
  `operationally_allowed`, `operational_degraded_reason`, and
  `research_certification_state`.
- Classification: certified full approval → `CERTIFIED_ACTIONABLE/NO_ACTION`; explicit
  provisional policy → `PROVISIONAL_ACTIONABLE/NO_ACTION`; otherwise
  `VALID_ANALYSIS_NON_ACTIONABLE`.

## 9. Gates that remain absolute

Operational policy can never bypass:

- DATA quality gate;
- PIT validation / universe snapshot;
- future-observation check;
- alpha signal validity (provisional signals are blocked in non-operational mode);
- portfolio construction validity;
- risk model validity;
- decision/execution gates.

New invariant: `DailyQuantPipeline` blocks any
`PROVISIONAL_OPERATIONAL_APPROVED` signal when `operational_mode=False`.

## 10. Regression results

- Full pytest: **741 passed** (baseline 727 + 14 new operational policy tests).
- Ruff: pass.
- Strict mypy: pass (372 source files).
- Secret scan: `SECRET_SCAN_PASS`.
- Real daily run without policy: `VALID_ANALYSIS_NON_ACTIONABLE`, 0 actions, no new
  policy/approval files.
- CLI `operational-policy show/set` verified in an isolated temporary config.

## 11. Final git status

Working tree is clean after the final commits (only ignored runtime data remains).

## 12. Commits

- `f6e6b58` feat: add research provider selection and SEC EDGAR corpus layer
- `10bac4a` fix: bind provisional operational advice to explicit user policy
- `7197d52` docs: archive 2026-08-12 session reports and refresh evidence artifacts
- follow-up: chore (provisional daily run helper) + this report

## 13. Remaining P0/P1/P2

- P0: none.
- P1: TECH-002 (governance of future session reports; mitigated by history INDEX);
  TECH-003 (runtime evidence growth).
- P2: TECH-004/005/006/007 unchanged from `TECH_DEBT.md`.
