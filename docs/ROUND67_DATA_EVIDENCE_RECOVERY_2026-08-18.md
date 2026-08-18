# ROUND67 — Data Evidence Recovery

Date: 2026-08-18

Starting SHA: `5f67e77f03a8d16bcf3a273de349936b19c4c4b5`

Final SHA: the separate ROUND67 commit containing this report, recorded in the handoff.

Verdict: `BLOCKED_DATA_QUALITY`

## Scope

No factor, alpha, probability, portfolio, risk, cost, benchmark, universe,
rebalance, or execution semantics changed. The Production Quant Champion is
unchanged. LLM formal influence is `0`; Probability formal influence is `0`;
auto execution remains disabled; manual confirmation remains required.

## Inventory and dependency graph

Machine-readable inventory: [2026-08-18_round67_data_evidence_inventory.json](audits/2026-08-18_round67_data_evidence_inventory.json).

It records 18 quant-critical fields and 11 source contracts. The decision path
is calendar/session -> security identity/lifecycle -> membership -> raw OHLCV
and PIT actions -> timestamp-gated fundamentals/filings/news -> factor inputs
-> champion/shadow -> risk/cost/optimizer -> next legal execution price ->
manual confirmation -> portfolio update.

## Scorecard

- PIT integrity: `BLOCKED_DATA_QUALITY`
- Survivorship integrity: `BLOCKED_DATA_QUALITY`
- OOS integrity: `BLOCKED_OOS`
- Price integrity: `PASS_WITH_WARNINGS`
- Benchmark integrity: `BLOCKED_PIT`
- Fundamental timestamp integrity: `BLOCKED_PIT`
- News timestamp integrity: `PASS_WITH_WARNINGS`
- Tradability integrity: `BLOCKED_TRADABILITY`
- Corporate action integrity: `BLOCKED_PIT`
- Reproducibility: `PASS_WITH_WARNINGS`

Terminal scorecard: `python main.py data-evidence`.

## Evidence verdicts

PIT is blocked because the repository lacks complete versioned PIT corporate
actions, total-return vintages, historical fundamental/filing vintages, and a
same-PIT benchmark package. Missing inputs are never converted to neutral data.

Survivorship is blocked because complete historical membership, delisted
returns, and permanent-ID/ticker history are unavailable. Current listings are
not accepted as historical proof. Deterministic fixtures cover ticker
transitions, delisting cutoffs, and membership boundaries; they prove software
semantics only.

Locked OOS is blocked. `LockedOOSManifest` freezes dataset, model config,
feature schema, train/evaluation boundaries, embargo, timestamp, and hash. It
seals once only; repeated evaluation, mismatch, unsealed use, or post-hoc tuning
fails closed.

Tradability is blocked for certification. The gate rejects same-session fills,
calendar skips, missing opens, zero/invalid volume, halts, stale quotes,
unrecorded symbol transitions, and benchmark-session mismatches.

## ROUND62 / ROUND65 reassessment

ROUND62 remains `STILL_BLOCKED`:

- `CERTIFIED_RESEARCH_MANIFEST_REQUIRED`
- `PIT_TOTAL_RETURN_HISTORY_INCOMPLETE`
- `HISTORICAL_MEMBERSHIP_INCOMPLETE`
- `LOCKED_OOS_NOT_FROZEN`

ROUND65 remains `STILL_BLOCKED`:

- `CERTIFIED_PIT_DATASET_REQUIRED`
- `HISTORICAL_MEMBERSHIP_INCOMPLETE`
- `LOCKED_OOS_NOT_CERTIFIABLE`
- `LOCKED_OOS_SAMPLE_INSUFFICIENT`
- `PROBABILITY_FORWARD_EVIDENCE_INSUFFICIENT`
- `LLM_FORWARD_EVIDENCE_INSUFFICIENT`
- `ADAPTIVE_PARTICIPATION_OOS_NOT_VALIDATED`

No model was promoted.

## Promotion constraints

Promotion requires one reproducible bound package with complete PIT prices,
actions, total-return vintages, and same-session benchmarks; historical
membership/delisting/identifier history; timestamped fundamentals, filings,
and formal events; verified open tradability; a sealed independent locked OOS
with sufficient sessions; deterministic dataset/config/schema replay; and all
existing after-cost, risk, decision, and manual-execution gates.

## Changed files

- `src/personal_alpha_terminal/research/data_evidence.py`
- `src/personal_alpha_terminal/research/__init__.py`
- `src/personal_alpha_terminal/terminal/cli.py`
- `tests/unit/research/test_round67_data_evidence.py`
- `docs/audits/2026-08-18_round67_data_evidence_inventory.json`
- `docs/ROUND67_DATA_EVIDENCE_RECOVERY_2026-08-18.md`

Inherited uncommitted `.gitignore`, Alpha Engine 2, test, and audit changes
were preserved and excluded from ROUND67.

## QA

Passed: ROUND67 tests `6 passed`; Alpha Engine 3 `6 passed`; ROUND65 tournament
`5 passed`; full Ruff; strict mypy (`505` source files); secret scan; JSON parse
(`18` fields, `11` sources); deterministic locked-OOS manifest checks.

The historical PIT suite passed 16 tests before a pre-existing runtime cleanup
failure: `.codex-temp/r7-version-registry` cannot be removed (`WinError 5`).
Full pytest reached 36% with widespread runtime-write errors after the managed
Windows sandbox denied test/runtime writes. `data-evidence --output` likewise
returns `PermissionError` for temporary/documentation paths in this sandbox.
These environment blocks were not converted into a product pass.
