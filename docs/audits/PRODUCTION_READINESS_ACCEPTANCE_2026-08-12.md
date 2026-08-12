# Production Readiness Acceptance — 2026-08-12

## Executive Summary

Personal Alpha Terminal has been moved from "development project" to a daily
operable personal production terminal. TECH-001/002/003 are closed, runtime
evidence is governed by an explicit, dry-run-by-default policy, and both
fail-closed (no policy) and degraded-research (explicit policy) daily runs were
executed against the real environment with the real `main` ledger. The terminal
can now produce real, portfolio-aware manual recommendation lists when an
explicit operational policy exists; it never auto-executes and never fabricates
data, probability, fills, or research certification.

Final verdict: `PRODUCTION_READY_DEGRADED_RESEARCH`.

## Baseline

- Branch: `codex/quant-core-closure-part1`
- HEAD at start: `0e93555`
- Git status: clean
- Operational policy: `NOT_CONFIGURED` (fail-closed default)
- Research certification: `NOT_CERTIFIABLE`
- Prior full pytest: 741 passed

## TECH-002 Resolution

- Session reports archived under `docs/history/2026-08-12-session/`.
- `docs/history/INDEX.md` created with phase registry and explicit rule that
  ordinary changes use Git commits only.
- `AGENTS.md`, `README.md`, and `REPOSITORY_GUIDE.md` now mandate the report
  lifecycle: current truth in the five canonical docs, audits under
  `docs/audits/YYYY-MM-DD_<topic>.md`, superseded reports under
  `docs/history/`, automated artifacts never in `docs/`.

## TECH-003 Resolution

- `core.retention.RUNTIME_ARTIFACT_POLICY` classifies every runtime evidence area.
- `python main.py maintenance artifacts status` inventories areas/files/sizes.
- `python main.py maintenance artifacts cleanup --dry-run` shows candidates
  without deleting; `--commit` applies deletion only to eligible generated
  evidence.
- CRITICAL areas (ledger DB, `var/operational`, `var/research-data`, backups,
  `artifacts`, `reports/validation-artifacts`) are never eligible.
- CACHE (`data/cache`) is reported but never auto-pruned.
- Four new retention regression tests prove dry-run non-mutation, commit
  boundaries, and critical protection.

## Runtime Artifact Policy

| Category | Areas | Retention |
|---|---|---|
| CRITICAL | var DB, operational, research-data, backups, artifacts, validation-artifacts | NEVER |
| DAILY_REPRODUCIBILITY | reports/daily-runs, data-snapshots, research-runs | 180 days |
| DIAGNOSTIC | var/logs, diagnostics, updates | 30 days |
| CACHE | data/cache | reported only |

Real `maintenance artifacts status` (2026-08-12): 736 daily-run files (10.89 MB),
48 data-snapshot files, 12 research-run files, 5 cache files, 105 research-data
files (37.40 MB), 710 backups, 1 validation artifact; dry-run showed 0 deletions.

## Operational Policy Validation

- `operational-policy show` and `operational-policy set` verified in isolated
  config; re-set without `--force` refuses overwrite.
- Policy evaluation now uses the run `decision_time` (not wall clock), making
  expiry deterministic and PIT-consistent.
- Regression tests cover: expired policy, missing policy, BLOCK decision,
  identity mismatch on every bound field (strategy version, factor hash,
  universe policy, lookbacks, portfolio/risk/cost hashes), and hash round-trip.
- Real acceptance policy:
  `operational-policy-129237232b6593e50473`
  `ALLOW_PROVISIONAL`, expires `2026-08-19T00:00:00+00:00`,
  `full_research_certified=false`.

## Gate Matrix

Documented in `docs/ARCHITECTURE.md` and enforced by the pipeline:

| Gate | PASS | FAIL |
|---|---|---|
| CALENDAR | continue | BLOCK |
| DATA | continue | BLOCK |
| PIT | continue | BLOCK |
| FUTURE DATA | continue | BLOCK |
| FEATURE | continue | BLOCK |
| FACTOR | continue | BLOCK |
| SIGNAL | continue | BLOCK |
| RESEARCH CERT | normal | policy evaluation |
| OPERATIONAL POLICY | continue | BLOCK |
| PORTFOLIO | continue | BLOCK |
| RISK | continue | BLOCK |
| DECISION | manual list | BLOCK |
| EXECUTION | manual only | no auto order |

`ALLOW_PROVISIONAL` cannot bypass any production gate.

## No-Policy Daily Run

Executed with `main` ledger and real certified data before issuing any policy:

- Classification: `VALID_ANALYSIS_NON_ACTIONABLE`
- Actions: 0
- No policy/approval file was created by the run
- Ledger unchanged (NAV/cash $100,000, 0 positions)

## Allow-Provisional Daily Run

Executed after the explicit 7-day policy was set:

- Run: `daily-51f740d1f2e34ca79869002eb24def01`
- Classification: `PROVISIONAL_ACTIONABLE`
- Operational policy: `operational-policy-129237232b6593e50473`
- Research state: `NOT_CERTIFIABLE`; `full_research_certified=false`
- Actions: 3 BUY (AAPL 19 sh, GOOGL 34 sh, JNJ 46 sh)
- Each recommendation includes target/current weight, delta, estimated value,
  estimated quantity, reference price, expected alpha, estimated cost, risk
  contribution, earliest execution time, model version, and reason.
- Portfolio ledger unchanged (recommendations only).
- No auto-issued approval was created; the old pre-hardening registry artifact
  was archived and the registry is not recreated by daily runs.

## Recommendation Pipeline

Recommendations flow from the real deterministic pipeline: PIT features,
cross-sectional factors, alpha candidates, portfolio construction, risk,
decision, and TradeGenerator with the configured transaction-cost model.
`estimated_cost` is present on every leg (e.g. AAPL $3.30, GOOGL $6.61, JNJ
$6.63), proving cost/slippage/turnover constraints participate in the outputs.
Confidence is honestly 0.0 because no calibrated probability artifact exists.

## Portfolio Awareness

Daily runs read the real `main` manual ledger (NAV/cash $100,000, 0 positions)
and produce current-weight-to-target-weight deltas from it. No paper/mock
portfolio exists. A missing portfolio blocks with `POSITION_INITIALIZATION_REQUIRED`
semantics rather than inventing positions.

## User Decision Flow

`DecisionService.review()` persists the user's ACCEPT/REJECT/WATCH decision and,
for accepted actionable recommendations, creates a pending manual-execution
order. `mark_executed()` is the only path that records a fill, requires a real
price, quantity, timestamp, and fees, and only then updates holdings/cash.

## Manual Execution Boundary

No broker connector or auto-order path exists. Acceptance never equals fill.
E2E I asserts: accepted recommendation changes `review_status` to `accepted`,
creates a pending order, produces zero fills, and leaves positions/cash
unchanged.

## LLM Failure Isolation

LLM is optional. When provider/schema/budget fails, the pipeline reports
`OPTIONAL_UNAVAILABLE`/`PASS_DEGRADED` and continues with the classical Quant
Core. Existing failure tests and the daily renderer preserve this boundary.

## External Data Failure Behavior

Provider/network failures surface as explicit BLOCKED/DEGRADED status with
provenance; there is no fake-data fallback. Real provider fallback remains
provider-to-provider with source identity preserved.

## Quant Regression

No factor, alpha, probability, portfolio, risk, cost, benchmark, universe, or
rebalance logic was changed. The only behavioral change is policy evaluation
time (decision_time instead of wall clock), which makes expiry deterministic
and is covered by tests. Factor rows and recommendation contents in the real
run match the pre-policy diagnostic factor ranking (GOOGL/AAPL/JNJ/JPM top).

## Full Test Results

- Full pytest: **762 passed** (741 baseline + 21 new: 4 retention, 8 identity
  binding, 9 product acceptance E2E A-I)
- Ruff: PASS
- Strict mypy: PASS (372 source files)
- Secret scan: PASS
- CLI smoke: daily, operational-policy, maintenance artifacts status/cleanup
  all exercised

## Remaining Tech Debt

- P0: 0
- P1: 0 (TECH-001/002/003 resolved)
- P2: TECH-004 (legacy root CLI), TECH-005 (legacy scripts package),
  TECH-006 (cross-package duplicate module names), TECH-007 (dual venvs)

## Final Verdict

`PRODUCTION_READY_DEGRADED_RESEARCH`

Full research certification is still missing (honest `NOT_CERTIFIABLE`), but the
explicit operational policy is valid, all production data/PIT/signal/portfolio/
risk gates pass, recommendation/decision/manual-execution boundaries are real,
and daily runs can now produce genuine manual trade lists for the `main` ledger.
