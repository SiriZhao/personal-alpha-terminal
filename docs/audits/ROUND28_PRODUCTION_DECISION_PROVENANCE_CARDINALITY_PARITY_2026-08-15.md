# ROUND28 — Production Decision Provenance / Cardinality Audit / Runtime Parity

## Verdict

`ROUND28_READY_FOR_INTELLIGENCE_EXPANSION`.

The three P0 objectives are implemented and evidenced:

- `CARDINALITY_INTEGRITY = PASS`
- `DECISION_PROVENANCE = PASS_WITH_NOT_PERSISTED_ROUND27_FIELDS`
- `RUNTIME_PARITY = PASS_WITH_LLM_QUARANTINE`

## ROUND28 Final Closure Repair

The previous partial status was caused by a docs provenance inconsistency, not
by a quant integrity defect:

- `docs/CURRENT_STATUS.json` and `docs/CURRENT_STATUS.md` were deleted from the
  working tree while tests and scripts still treated them as canonical.
- The HEAD versions were stale (2026-08-09, `SHADOW_ONLY`, 516 passed), so a
  blind restore would have produced a false status.
- `AGENTS.md`, `README.md`, `docs/history/INDEX.md` and older audits referenced
  root `ARCHITECTURE.md`, `REPOSITORY_GUIDE.md` and `TECH_DEBT.md`, but those
  files were absent from the working tree.

Fixes applied:

- Added a build path to `scripts/generate_current_status.py` that derives
  `docs/CURRENT_STATUS.json` from `round27_acceptance_manifest.json` and the
  ROUND27 acceptance `run_certificate.json`.
- Regenerated `docs/CURRENT_STATUS.json` and `docs/CURRENT_STATUS.md` from the
  real ROUND28 runtime evidence.
- Added a consistency test that verifies CURRENT_STATUS against the manifest
  and certificate, including 1,171 optimizer input, no fixed cap, 10 formal
  actions and `probability_production_influence = 0.0`.
- Restored the three root canonical docs referenced by AGENTS and history:
  `ARCHITECTURE.md`, `REPOSITORY_GUIDE.md`, `TECH_DEBT.md`.
- Updated stale references in README, docs README, user guide and history index
  to current canonical paths. Historical development reports were not
  restored.

## Files changed in this closure

- `ARCHITECTURE.md`, `REPOSITORY_GUIDE.md`, `TECH_DEBT.md` (new root canonical
  docs)
- `docs/CURRENT_STATUS.json`, `docs/CURRENT_STATUS.md` (regenerated from
  runtime artifacts)
- `scripts/generate_current_status.py` (added artifact-backed build path)
- `tests/unit/test_current_status_document.py` (added consistency assertions)
- `README.md`, `docs/README.md`, `docs/USER_GUIDE_ZH_CN.md`
- `docs/audits/PRODUCTION_READINESS_ACCEPTANCE_2026-08-12.md`,
  `docs/audits/WORKTREE_RECONCILIATION_AND_TECH001_2026-08-12.md`
- `docs/history/2026-08-12-session/INDEX.md`
- `reports/validation-artifacts/round28_validation_summary.json`
- `docs/audits/ROUND28_PRODUCTION_DECISION_PROVENANCE_CARDINALITY_PARITY_2026-08-15.md`

## Canonical artifact disposition

- Retained and regenerated: `docs/CURRENT_STATUS.json`, `docs/CURRENT_STATUS.md`.
- Restored as root current truth: `ARCHITECTURE.md`, `REPOSITORY_GUIDE.md`,
  `TECH_DEBT.md`.
- Retained as runtime artifacts: `reports/daily-runs/*`,
  `reports/validation-artifacts/*`.
- Left deleted without replacement: historical development reports that are no
  longer current truth and are not referenced by active runtime/test code.

## Git diff summary

The working tree remains uncommitted on `codex/round27-31`. Current diff shows
56 files changed with approximately 2,052 insertions and 2,993 deletions,
including pre-existing ROUND27/ROUND28 source/test changes already present
before this closure. No new unrelated source or quant changes were introduced
by this closure.

## 1. Is there a hard 10-position limit?

No.

- Code: `PortfolioConstraints` has no position-count field.
- Config: `config.yaml` and `config.example.yaml` contain no
  `max_positions`, `max_holdings`, `top_n` or `head(10)`.
- Policy: `var/operational/policy-artifacts/527ff899...json` contains no
  cardinality cap.
- Runtime: `cardinality_trace.maximum_allowed_holdings = null`,
  `holding_cap_policy = NO_FIXED_CARDINALITY_CAP`.

The only `[:10]` in the production daily chain is `candidates`/display, which
is explicitly recorded as `display_candidates_limited_to = 10` and is not
passed into the optimizer.

## 2. Why exactly 10 formal actions in ROUND27?

The optimizer received all 1,171 candidates. The final 10 are natural
optimizer/constraint sparsity:

- risk aversion = 3.0
- turnover penalty = 0.01
- transaction-cost model in the SLSQP objective
- no-trade band = 0.005
- minimum rebalance weight = 0.01
- minimum trade value = 100.0
- current portfolio is 100% cash, so every non-zero target is a full new trade

Minimum final weight is 1.23%; minimum estimated trade notional is $1,232.56.
No post-optimizer cost/risk/liquidity/execution drop is recorded.

## 3. Did all 1,171 candidates enter the optimizer?

Yes.

- `candidate_count = 1171`
- `optimizer_input = 1171`
- `risk_engine_securities = 1171`
- `pre_optimizer_top10_truncation = false`
- `optimizer_received_alpha_top10 = false`
- Candidate compression: 2,135 factor-ranked -> 1,174 alpha-positive -> 1,174
  min-alpha -> 1,171 liquidity -> 1,171 optimizer-eligible

## 4. What did each final stock pass through?

The generated
`reports/daily-runs/daily-2420c68452d142298e6b42482341391f/decision_provenance.json`
contains 2,135 factor rows, including all 10 formal decisions. Each record
includes factor inputs, composite, rank, expected alpha, signal eligibility,
probability state, risk contribution, cost evidence, current-only size/sector,
optimizer/constrained target, execution target, reasons, vetoes, gates and
hashes.

For example, VSTS:

- factor rank = 1
- raw expected alpha = 0.045512535876053264
- covariance/risk contribution = 0.3294695448956056
- final target = 0.06909927636475353

ROUND27 snapshots did not persist per-symbol annualized volatility, beta or ADV;
those fields are explicitly marked `NOT_PERSISTED_IN_ROUND27_SNAPSHOT` instead
of being estimated.

## 5. Why does probability have no production influence?

The probability overlay is `RESEARCH_ONLY`, reason
`PROBABILITY_FALLBACK_CLASSICAL:NO_INCREMENTAL_ALPHA`, production influence 0%.
The decision provenance records target-with/without probability as identical.

## 6. Why is gross only about 27.2% when target vol is 15%?

Target volatility is an upper bound, not a leverage target. The optimizer
maximizes risk-adjusted alpha minus variance, turnover and transaction costs.
With a 100% cash start, every position is a full new trade, so useful gross
stops at 27.23%; achieved expected vol is 7.60%.

No numeric constraint is binding:

- target vol 15% vs achieved 7.60%
- max gross 90% vs achieved 27.23%
- min cash 10% vs achieved 72.77%
- max position 12% vs largest 6.91%
- max turnover 30% vs estimated 27.23%
- max HHI 18% vs achieved 1.01%

Active limitations: `size_neutralization:degraded` and current-only sector
concentration not used by the optimizer.

## 7. Acceptance vs real production daily run

`reports/validation-artifacts/production_runtime_parity.json` compares
`daily-2420c68452d142298e6b42482341391f` with
`daily-74e83bb34b014a13a8520c0c377101df`.

- formal actions, target weights, risk contributions, estimated values and
  estimated costs: identical
- gross/cash/expected vol/HHI/largest target: identical
- probability state: identical
- news input facts: identical
- config/model/policy identities: identical
- AI status: acceptance PASS vs production PASS_DEGRADED whole fallback
- production semantic grounding:
  `AI_BRIEF_QUARANTINED_SEMANTIC_MISMATCH`

The production brief was correctly quarantined because it claimed
`19.17% / 80.25% / 27.23%` while formal facts are
`19.24% / 80.28% / 27.23%`. The LLM did not change formal decisions.

DecisionManifest replay passes for both runs. Semantic hashes differ only
because the production run refreshed data (different data hash/snapshot);
formal decision fields remained unchanged.

## 8. Test results

- ROUND28/27 targeted: 26 passed
- quant-critical: 31 passed
- quant regression (`tests/unit/quant_engine tests/integration`): 317 passed
- future leakage suite: 14 passed
- semantic isolation suite: 40 passed
- CURRENT_STATUS consistency tests: 2 passed
- full pytest: 1,194 passed
- ruff: PASS
- mypy strict: PASS, 465 source files
- secret scan: `SECRET_SCAN_PASS`
- `git diff --check`: PASS (only LF/CRLF warnings)

## 9. Remaining known issues (non-blocking)

- ROUND27 decision provenance has a small set of `NOT_PERSISTED` per-symbol
  risk fields because the older snapshot did not serialize them; new runtime
  runs capture them via `DailyQuantOrchestrator._decision_provenance`.
- Disposable historical development reports remain deleted rather than
  restored; current canonical docs now point to root
  `ARCHITECTURE.md`, `REPOSITORY_GUIDE.md`, `TECH_DEBT.md` and
  `docs/audits/`.
- `.venv314` remains on disk pending a separate approved workspace cleanup.

## 10. Next round suggestions

1. Resolve the docs deletion provenance explicitly before any further closure.
2. Run one fresh production daily run so the new `decision_provenance.json`
   is produced entirely by `DailyQuantOrchestrator` without fallback markers.
3. Treat the production AI brief quarantine as expected behavior; do not relax
   semantic validation.
4. Add a governed portfolio cardinality policy only if a real research
   decision establishes one; do not invent a Top-N.
5. Keep probability research-only until mature OOS evidence exists.

## Artifacts

- `reports/validation-artifacts/cardinality_audit.json`
- `reports/validation-artifacts/risk_budget_utilization_audit.json`
- `reports/validation-artifacts/production_runtime_parity.json`
- `reports/daily-runs/daily-2420c68452d142298e6b42482341391f/decision_provenance.json`
- `docs/CURRENT_STATUS.json`
- `docs/CURRENT_STATUS.md`
- `reports/validation-artifacts/round28_validation_summary.json`
- `ARCHITECTURE.md`
- `REPOSITORY_GUIDE.md`
- `TECH_DEBT.md`

## Final status

`ROUND28_FINAL_STATUS = PASS`

`CARDINALITY_INTEGRITY = PASS`

`DECISION_PROVENANCE = PASS_WITH_NOT_PERSISTED_ROUND27_FIELDS`

`RUNTIME_PARITY = PASS_WITH_LLM_QUARANTINE`

`FINAL_VERDICT = ROUND28_READY_FOR_INTELLIGENCE_EXPANSION`

`READY_FOR_ROUND29 = YES`
