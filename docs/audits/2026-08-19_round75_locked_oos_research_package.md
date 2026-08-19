# ROUND75 — Locked OOS Research Package

Date: 2026-08-19

## Verdict

**Engineering implementation: PASS.**

**Locked OOS research status: `BLOCKED_DATA_QUALITY` and `BLOCKED_OOS`.**

No locked OOS was opened, no result was inspected, no model was tuned, and no
alpha, probability, portfolio, risk, cost, benchmark, universe or execution
semantics changed. The Production Quant Champion remains unchanged; LLM and
Probability formal influence remain zero; execution remains manual-only with no
broker order path.

## Delivered protocol

- Added `research.locked_oos_protocol` with a content-addressed immutable
  manifest covering dataset ID/hash/vintage, feature schema hash, model
  ID/version/hash, config hash, train/validation/locked-OOS boundaries,
  purge/embargo/label horizon, historical-universe semantics, benchmark and
  return semantics, costs, slippage, execution-price policy, calendar,
  corporate-action semantics, creation time, seal state and manifest hash.
- Partitions are chronological and non-overlapping. `purge_sessions` must cover
  the configured label horizon; embargo is explicit. This rejects evaluation
  leakage across boundaries.
- A draft can be sealed only once and only after ROUND74 data certification is
  `PASS`. Sealed or evaluated manifests cannot be overwritten on disk.
- Opening returns an immutable audit record whether it is allowed or blocked.
  A blocked open does not consume OOS; every audit can be persisted with
  exclusive write-once mode.
- Replay inputs are checked against the frozen dataset, vintage, feature schema,
  model, config, universe, benchmark, transaction cost, slippage, execution,
  calendar and corporate-action assumptions. Any mismatch blocks opening.
- Evaluation can occur exactly once after a successful audited open. Repeated
  opening is blocked; post-hoc tuning after OOS is explicitly rejected.
- Added `main.py locked-oos --json [--manifest PATH]`, a status-only command
  that cannot open or evaluate OOS.

## Current state and exact blockers

`main.py locked-oos --json` reports `BLOCKED_DATA_QUALITY` because the ROUND74
certification status is `BLOCKED_DATA_QUALITY`; no legitimate immutable external
historical package has been bound. It also reports `LOCKED_OOS_MANIFEST_MISSING`.

Required before a real protocol may be sealed:

- permanent identity, ticker history, historical membership, delistings and
  delisted returns;
- raw PIT OHLCV, revisioned corporate actions, total-return vintages and a
  semantically aligned PIT benchmark;
- timestamped fundamental, filing and event inputs;
- next legal-session executable opens with volume/halt/tradability history;
- a bound, immutable import package certified `PASS` by ROUND74.

The machine-readable current status is
`docs/audits/2026-08-19_round75_locked_oos_status.json`.

## QA

- ROUND75 + ROUND74 + ROUND67 protocol/evidence tests: `23 passed`.
- Combined PIT, identity, membership, corporate-action, benchmark, timestamp,
  leakage, ROUND74 and ROUND75 suite: `77 passed`.
- Quant-critical production-contract suite: `6 passed`.
- `main.py locked-oos --json`: PASS as an operator command; returned the honest
  `BLOCKED_DATA_QUALITY`/manifest-missing state.
- Ruff: PASS.
- Strict mypy (ROUND74/75 sources and CLI): PASS, 4 source files.
- Secret scan: `SECRET_SCAN_PASS`.
- Final ROUND73 real normal-terminal regression: `4.804s` to usable local
  terminal frame (under the 10-second hard ceiling); remote refresh was detached
  and stale output remained non-actionable.

Fixture manifests and their sealed/evaluated examples prove software semantics
only. They do not represent a real dataset, OOS run, independent observation,
historical evidence or economic alpha. Full-suite status is not claimed by this
bounded round.
