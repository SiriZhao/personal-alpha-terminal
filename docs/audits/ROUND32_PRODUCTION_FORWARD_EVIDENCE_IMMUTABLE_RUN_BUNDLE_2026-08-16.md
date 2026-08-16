# ROUND32 — Production Forward Evidence / Immutable Run Bundle / Full Replay Inputs

## Verdict

`ROUND32_FINAL_STATUS = PASS`

`FINAL_VERDICT = ROUND32_FULL_REPLAYABILITY_ESTABLISHED`

`READY_FOR_ROUND33 = YES`

Every formal daily run from ROUND32 onward persists a complete immutable run
bundle; the ROUND32 acceptance run (`daily-33c600f064504fd9a71a596e36080fe6`)
was deterministically replayed from its persisted inputs with **bitwise-equal
optimizer outputs** (target weights, gross, cash, expected vol, HHI, turnover,
estimated cost, expected alpha).

## 1. Acceptance tokens

`reports/validation-artifacts/round32_run_bundle_audit.json`:

| Token | Status |
|---|---|
| ROUND32_FULL_REPLAY | REPLAY_PASS |
| RUN_INPUT_PERSISTENCE | PASS |
| NO_FUTURE_REHYDRATION | PASS |
| IMMUTABILITY | PASS |
| ROUND27_FULL_REPLAY | LEGACY_INPUT_INCOMPLETE |

`NO_PRODUCTION_POLICY_CHANGE` (this round only adds evidence infrastructure;
no quant semantics, optimizer inputs or policy parameters were changed).

## 2. What was built

### `application/run_bundle.py` (new)

- `ContentAddressedBlobStore`: SHA-256 content-addressed immutable blobs under
  `reports/evidence-bundles/blobs/`; atomic write via temp file + `os.replace`;
  identical content deduplicates; tampering is detected by hash verification.
- `stage_run_bundle()`: persists every optimizer input as blobs and writes a
  `STAGED` manifest under `reports/evidence-bundles/<run_id>/run_manifest.json`.
- `finalize_run_bundle()`: seals the manifest with the sealed
  DecisionManifest semantic hash; idempotent for identical content, refuses to
  mutate a sealed bundle otherwise.
- `replay_run_bundle()`: deterministic replay that re-runs the same
  `PortfolioConstructionEngine` from persisted inputs only; appends one
  append-only replay occurrence record (never predictions/outcomes).
- `verify_bundle_integrity()`: verifies every referenced blob exists and hashes
  to its digest.

### Persisted sections (13 blobs)

| Section | Persisted content |
|---|---|
| universe | decision timestamp, PIT cutoff, universe snapshot id, symbols, eligibility, data quality, pit_valid |
| authorization | full ResearchDataAuthorization (request, gate decision, evidence) |
| alpha | raw `AlphaSignal` rows (identity, raw/normalized signal, confidence, eligibility, model/data version) |
| risk | covariance + correlation matrices (npy blobs), returns window, benchmark returns, risk metadata (sector/ADV/size/market cap), vol, beta, condition number, shrinkage, limitations |
| liquidity | per-symbol ADV, participation assumption, max tradable weight, source timestamp |
| cost | TransactionCostConfig (commission, spread, impact, slippage, coefficients, version) |
| constraints | full PortfolioConstraints (target vol, max gross, min cash, max position, HHI, turnover, no-trade band) |
| portfolio | current weights, portfolio value, operational mode, risk state, regime, evaluated risk budget, raw/constrained/final targets, optimizer provenance |

### Orchestrator wiring

- `ProductionDailyWorkflow.run()` accepts `run_identity` and stages the bundle
  after the deterministic pipeline succeeds (fail-soft: a staging failure
  leaves no sealed bundle and never fabricates one).
- `DailyQuantPipeline` exposes the evaluated `risk_budget` on
  `DailyQuantOutput` so replay uses the exact budget the optimizer saw.
- `DailyOrchestrator` seals the bundle with the DecisionManifest hash after
  `_build_result` and records the `evidence_bundle` reference in
  `decision_provenance.json`.

### CLI

- `python main.py run-bundle list|show|replay|verify <run_id>`
- `python main.py round32-audit --acceptance-run <run_id>`

## 3. Replay evidence (real 1171-candidate production run)

Run: `daily-33c600f064504fd9a71a596e36080fe6`

Decision manifest semantic hash: `b838d53b59bcfaf86c703b608ec8932d562b8b19ab8a63ba9a42348c2b73ba13`

Bundle hash: `6621195f6e5f40b30ff2e30119b7ec0e6005de1dbc16f52bb5be05c1013d628d`

| Metric | Recorded | Replayed | Passed |
|---|---:|---:|---|
| target_symbol_count | 10 | 10 | yes |
| target_weight_max_delta | – | 0.0 | yes (abs ≤ 1e-9) |
| gross | 0.27227518925316907 | 0.27227518925316907 | yes |
| cash_weight | 0.7277248107468309 | 0.7277248107468309 | yes |
| expected_volatility | 0.07600921627388443 | 0.07600921627388443 | yes |
| hhi | 0.01009067252678213 | 0.01009067252678213 | yes |
| turnover | 0.27227518925316907 | 0.27227518925316907 | yes |
| estimated_transaction_cost | 15.194881350479402 | 15.194881350479402 | yes |
| expected_alpha | 0.13947350852884594 | 0.13947350852884594 | yes |

Replay is strictly PIT-bounded: it reads only persisted blobs; a missing
original input yields `REPLAY_NOT_POSSIBLE_MISSING_ORIGINAL_INPUT`. There is no
provider, download or refresh path in the replay module.

## 4. Anti-leakage / idempotency

- Replay never appends predictions or outcomes; each replay writes exactly one
  `replay-occurrence-v1` row to `replay_occurrences.jsonl`.
- The same frozen bundle replays to the same semantic decision; two replay
  runs produced identical metrics (deterministic).
- The interrupted pre-recovery acceptance run (`daily-914ab7...`) remains
  `STAGED` (honest evidence of the interruption; replay refuses with
  `REPLAY_NOT_POSSIBLE_BUNDLE_NOT_SEALED`).

## 5. Consistency of the production decision chain

The ROUND32 acceptance run preserved the formal invariants:

- Optimizer input: `1171`; pre-optimizer Top-N: `null`; fixed holdings cap:
  `null`; final formal actions: `10` (optimizer-decided, not a fixed Top-10).
- Probability: `RESEARCH_ONLY`, production influence `0.0`
  (`PROBABILITY_FALLBACK_CLASSICAL:NO_INCREMENTAL_ALPHA`).
- Market regime: `OBSERVATION_ONLY`; LLM: `ADVISORY_ONLY`/SHADOW (cannot change
  production recommendations).
- ETF research: no formal ETF actions; automatic execution: DISABLED;
  broker order submission: DISABLED; manual confirmation: required.
- Portfolio: gross `27.23%`, cash after `$72,757.29`, expected vol `7.60%`.

## 6. Validation

- New unit tests: `tests/unit/application/test_round32_run_bundle.py`
  (8 passed) covering blob immutability/dedupe, serialization symmetry,
  stage/finalize/replay, idempotency (no predictions written), missing-blob
  anti-leakage, sealed immutability, legacy classification, unsealed rejection.
- Regression: ROUND28-31 application suites (35 passed).
- `ruff check .`: PASS
- `git diff --check`: PASS
- Secret scan: PASS (no new secrets; bundle blobs contain factor/covariance
  data only, no credentials).

## 7. Files changed

- `src/personal_alpha_terminal/application/run_bundle.py` (new)
- `src/personal_alpha_terminal/application/round32_audit.py` (new)
- `src/personal_alpha_terminal/application/quant_daily_service.py`
- `src/personal_alpha_terminal/application/daily_orchestrator.py`
- `src/personal_alpha_terminal/quant_engine/production_pipeline.py`
- `src/personal_alpha_terminal/terminal/cli.py`
- `tests/unit/application/test_round32_run_bundle.py` (new)

## 8. Known limitations

- ROUND27-era runs (`daily-2420c68452d142298e6b42482341391f` and earlier)
  cannot be fully replayed: `LEGACY_INPUT_INCOMPLETE` (not fabricated).
- The bundle stores the full covariance/correlation/returns panels; storage
  growth is bounded by content-addressed deduplication across runs.
- `mypy --strict` for the full package is reported in the round validation
  summary; the new module passes strict typing checks.

## 9. Evidence artifacts

- `reports/evidence-bundles/daily-33c600f064504fd9a71a596e36080fe6/run_manifest.json`
- `reports/evidence-bundles/daily-33c600f064504fd9a71a596e36080fe6/replay_occurrences.jsonl`
- `reports/validation-artifacts/round32_run_bundle_audit.json`
- `reports/validation-artifacts/run_bundle_replay_daily-33c600f064504fd9a71a596e36080fe6.json`
- `reports/daily-runs/daily-33c600f064504fd9a71a596e36080fe6/` (certificate +
  decision_provenance.json with the sealed `evidence_bundle` reference)

## 10. Git status

See commit `ROUND32: production forward evidence infrastructure` (baseline
ROUND27-31 work reconciled in the same branch before the round commit).
