# ROUND78 — Controlled Intelligence Promotion Tournament

Date: 2026-08-19

## Verdict

**Engineering implementation: PASS.**

**Economic promotion: `BLOCKED_DATA_QUALITY`.** The required certified
PIT/survivorship/tradability/benchmark package, sealed-and-executed locked OOS
manifest and certified production-parity replay panel are not available. No
policy was promoted, no historical or forward economic result was invented, and
fixtures prove only the tournament software semantics.

## Delivered controlled tournament

- Added `research.intelligence_tournament`, a fail-closed layer over the ROUND71
  immutable `DecisionFreeze` / `TournamentDecision` contract. It requires the
  five synchronized policies: `PURE_QUANT`, `QUANT_PLUS_PROBABILITY`,
  `QUANT_PLUS_LLM`, `QUANT_PLUS_PROBABILITY_PLUS_LLM`, and
  `FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE`.
- Existing ROUND71 immutable decision ID, model/config hash, frozen timestamp,
  information-cutoff, universe, benchmark, execution, cost and accounting
  validation remains authoritative. Duplicate policies, rewrites and outcomes
  before their decision are rejected.
- Structured LLM market/company/portfolio evidence now requires source,
  observed time, available time, freshness, evidence ID, content hash and
  confidence. Missing, malformed, stale, future, duplicate or conflicting
  evidence fails soft to Quant; it cannot reuse stale output.
- The LLM ladder is explicit: `L0_COMMENTARY`, `L1_SHADOW_SCORING`,
  `L2_RANKING`, `L3_BOUNDED_FORMAL`, `L4_ADAPTIVE_EVIDENCE`. L0-L2 cannot
  create formal LLM influence. Any L3/L4 request still requires certified
  synchronized evidence, hard-risk authority, manual confirmation and disabled
  auto execution.
- Probability, LLM and Adaptive Exposure are assessed from paired after-cost
  metrics against the shared `PURE_QUANT` baseline. Gates require paired sample
  size/session count, return and benchmark-excess value add, drawdown/turnover/
  cost bounds and a non-negative paired confidence lower bound. Adaptive
  Exposure additionally requires stable regimes, incremental bull/upside and
  recovery participation, and no material downside-capture regression.
- Alpha Engine 3 remains a distinct challenger attribution record, measured
  against the frozen Pure Quant baseline; it cannot silently become a policy or
  production champion.
- Added read-only `main.py intelligence-tournament [--json]`, which neither
  opens locked OOS nor submits an order nor calls a remote provider.

## Current synchronized comparison

The following status is intentionally not an economic comparison: no certified
paired panel exists, so all deltas and intervals remain missing.

| Policy | Sample count | Return delta | Excess delta | Sharpe delta | Max DD delta | Upside capture delta | Downside capture delta | Turnover delta | Cost delta | Exposure delta | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| PURE_QUANT | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | BLOCKED_DATA_QUALITY |
| QUANT_PLUS_PROBABILITY | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | BLOCKED_DATA_QUALITY |
| QUANT_PLUS_LLM | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | BLOCKED_DATA_QUALITY |
| QUANT_PLUS_PROBABILITY_PLUS_LLM | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | BLOCKED_DATA_QUALITY |
| FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | BLOCKED_DATA_QUALITY |

## Authority status

- PRODUCTION POLICY: `PURE_QUANT`.
- ALPHA ENGINE 3: `RETAIN_SHADOW`; separate paired attribution is unavailable
  (`ALPHA_ENGINE3_PAIRED_MEASUREMENT_REQUIRED`).
- PROBABILITY: `RETAIN_SHADOW`; formal influence `0.0`.
- LLM LEVEL: `L1_SHADOW_SCORING`; formal influence `0.0`.
- ADAPTIVE EXPOSURE: `RETAIN_SHADOW`.
- STRONGEST CHALLENGER: N/A.
- PROMOTION REASON/BLOCKER: `CERTIFIED_DATA_FOUNDATION_REQUIRED`,
  `LOCKED_OOS_PROTOCOL_REQUIRED`, `LOCKED_OOS_MANIFEST_MISSING`,
  `CERTIFIED_REPLAY_REQUIRED`, and no paired `PURE_QUANT` baseline.

Manual confirmation remains required; `AUTO_EXECUTION=DISABLED`; no broker
submission path was added. Long-only, hard risk/liquidity/portfolio constraints,
no fixed pre-optimizer Top-N, no fixed holdings-count cap and the Production
Quant Champion are unchanged.

## QA and runtime evidence

- ROUND78 tournament tests: `8 passed`.
- ROUND71 plus ROUND74-78 research/PIT/OOS/replay/diagnosis regression subset:
  `47 passed`.
- Agentic/LLM, Probability, Adaptive Exposure and portfolio-risk regression
  subset: `98 passed`.
- Isolated terminal fast-start/CLI/startup/session suites: `40 passed`.
- Quant-critical production-contract suite: `6 passed`.
- `main.py intelligence-tournament --json`: passed as a read-only status
  command and truthfully reported `BLOCKED_DATA_QUALITY` with zero formal LLM
  and Probability influence.
- Ruff: `PASS` for `src`, `tests` and `main.py`.
- Strict mypy: `PASS`, 515 source files.
- Secret scan: `SECRET_SCAN_PASS`.
- `main.py doctor`: completed; it reported existing `Cache`, `Reports` and
  `Var` permission errors without exposing any secret value.
- Real normal launcher path is `run_terminal.bat`, which calls
  `.venv\Scripts\python.exe -u main.py`. Direct real entry point
  `.venv\Scripts\python.exe main.py` rendered the usable local terminal frame
  in `5.174s` (ROUND77 reference: `4.664s`), under the 10-second ceiling. It
  correctly displayed cached recommendations as non-actionable. In this local
  environment refresh scheduling failed fast because the refresh-state path
  under `C:\Users\YOGA Pro16\AppData\Local\PersonalAlphaTerminal\run` is
  denied; the useful degraded diagnostic appeared within the same 5.174 seconds
  and no provider wait occurred.

One broad legacy file, `tests/unit/test_terminalization_stage1.py`, did not
finish within the bounded local attempt after its first test completed; its
verified test worker was stopped and is **not** counted as a pass. This is an
inherited CPU-heavy regression-test runtime issue outside the ROUND78 source
surface. The focused terminal and production-contract checks above completed.

Machine-readable current status:
`docs/audits/2026-08-19_round78_intelligence_tournament_status.json`.
