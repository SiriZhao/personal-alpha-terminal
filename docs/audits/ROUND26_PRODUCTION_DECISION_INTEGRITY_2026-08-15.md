# ROUND26 — PRODUCTION DECISION INTEGRITY / PROBABILITY FORWARD CALIBRATION /
# CURRENT EXPOSURE RISK / AI GROUNDING / NEWS ACQUISITION / FULL QUALITY CLOSURE

Date: 2026-08-15 (Asia/Shanghai)
Branch: `codex/round25etf` (branch kept; no product version bump, no tag/release)
Baseline: `var/backups/round26-baseline-20260815T050000Z/` (git HEAD `f2fff9d`)

## 1. ROUND26 verdict

`ROUND26_READY_PROVISIONAL_FORWARD_VALIDATION`

Decision integrity, deterministic replay, drift attribution, forward
probability ledger, honest current size/sector exposure accounting, AI facts
contract + section-level quarantine, real official macro news acquisition and
full quality closure all completed.  No nondeterminism, no future leakage,
no formal/research leakage, no AI trade authority, and the DecisionManifest
is consistent across the chain.

## 2. git baseline

HEAD `f2fff9d` (ROUND25 final report), branch `codex/round25etf`, worktree CLEAN.

## 3. latest daily run id

`daily-02d41626e82b4238916e78620fdae1e5`

## 4. DecisionManifest status

PASS. Sealed immutable manifest per run (schema `decision-manifest-v1`) with
snapshots/hashes/model ids/policy ids/solver/formal action ids/execution plan
id + semantic hash; persisted as `decision_manifest.json` and embedded in
`run_certificate.json`.

## 5. Decision semantic hash

`6d937770657e27eac9e423d16cd2ac4eec14e304780a228c40c52fb392e0fc49`

## 6. deterministic replay result

`REPLAY_PASS` (manifest hash == recomputed hash from certificate inputs).

## 7. repeated-run action consistency

Repeated same-snapshot runs produce identical formal symbols/actions/
quantities; target-weight tolerance ≤ 4.8e-6 (SLSQP tolerance, ROUND25-verified
against baseline).  Small-universe fixtures bit-identical (miniature golden
and round5 tests).

## 8. decision drift attribution status

Implemented: `python main.py decision-diff <old> <new>` compares two run
certificates (market data / portfolio / universe / config / model / policy
changes, action add/remove/change, weight changes) and classifies
DATA_CHANGE / UNIVERSE_CHANGE / PORTFOLIO_CHANGE / CONFIG_CHANGE /
MODEL_CHANGE / POLICY_CHANGE / NONDETERMINISM_SUSPECTED; writes
`reports/validation-artifacts/decision_diff.json`.

## 9. reason ROUND25/run differences can now be explained

Drift between runs is attributed to concrete input changes (e.g. the 9→10
action change tracks the refreshed market-data snapshot `2eb80a04...` vs the
ROUND24 baseline `da672c71...`); identical semantic inputs with different
actions now raise NONDETERMINISM_SUSPECTED instead of being silently ignored.

## 10. run-certificate UNKNOWN remaining count

0. Evidence refs are now `run:<run_id>` / `decision:<decision_id>` /
`decision-manifest:<hash16>`; deterministic builders never emit UNKNOWN.

## 11. full formal stock actions

10 STOCK BUY (latest run, refreshed data): ATEX, CDNA, DK, LQDA, RLAY, RVMD,
STX, TVTX, UMC, VSTS — EQUITY_ALPHA, manual execution only.

## 12. optimizer candidate count

Optimizer receives the full eligible alpha set (no truncation); latest
provisional signals 1173, factor-eligible 2133, 10 final targets (natural
optimizer sparsity).

## 13. fixed holdings cap

None (NO_FIXED_CARDINALITY_CAP preserved).

## 14. pre-optimizer Top-N

None (invariant test `test_production_assembler_receives_full_eligible_set`).

## 15. optimizer cardinality cap

None.

## 16. Probability model status

PASS_DEGRADED / PROBABILITY_FALLBACK_CLASSICAL / NO_INCREMENTAL_ALPHA
(fail-safe).

## 17. Probability production weight

0.

## 18. new forward predictions

38 immutable `ProbabilityPrediction` rows (append-only ledger
`var/probability-forward/predictions.jsonl`), one per formal recommendation at
decision time.  Frozen target: P(21-session forward SPY-relative return after
estimated transaction cost > 0) — the project's existing horizon convention.

## 19. matured Probability outcomes

0 (correct: the horizon has not elapsed; no fabricated outcomes).

## 20. Brier score if available

N/A (no matured outcomes).

## 21. ECE if available

N/A (no matured outcomes).

## 22. Probability incremental after-cost Alpha if available

N/A (0 production influence; counterfactual machinery ready).

## 23. Probability promotion status

NOT_ELIGIBLE. 15-condition `ProbabilityPromotionPolicy`; AUTO_PROMOTE
forbidden; human approval required; progressive capped levels (0/5/10/15%)
architected but none enabled.

## 24. Size coverage

0% (UniverseMembership table has no market-cap rows). Honest
`SIZE_RISK_DEGRADED`, never PASS, missing never assumed large-cap.

## 25. portfolio unknown size weight

1.0.

## 26. portfolio small/micro exposure

0.0 (reported; coverage-degraded).

## 27. Sector coverage

0% (no verifiable full-universe issuer SIC feed available). SEC SIC → normalized
sector mapping implemented (`sec-sic-divisions-v1`), unknown stays UNKNOWN.

## 28. portfolio unknown sector weight

1.0.

## 29. top sector exposure

UNKNOWN (coverage-degraded).

## 30. sector HHI

1.0 (single UNKNOWN bucket).

## 31. historical size PIT status

Unchanged: SIZE_EXPOSURE_UNAVAILABLE for historical PIT. Current operational
evidence is strictly separated (`CURRENT_OPERATIONAL`) and never written to
historical PIT tables.

## 32. historical sector PIT status

Unchanged: SECTOR_EXPOSURE_NOT_VALIDATED for historical PIT. Current SIC
mapping is never used for historical neutralization.

## 33. AI model/provider

deepseek-v4-flash (ADVISORY/EXPLANATION; authority NONE).

## 34. DeepSeek calls

4 per daily run (PASS1 facts / PASS2 risk critic / PASS3 market-news synthesis
/ PASS4 final brief). Latest: 22,048 prompt + 10,143 completion tokens.

## 35. AI grounding PASS/DEGRADED

PASS_DEGRADED: live PASS4 outputs were schema-invalid and the whole brief fell
back to the deterministic v2 brief, which itself passes semantic grounding
(AI_SEMANTIC_GROUNDING_OK) after the ticker word-boundary fix.

## 36. AI quarantined sections

0 in the final fallback (whole-brief fallback for schema-invalid PASS4).
Section-level quarantine is implemented and unit-tested: healthy DeepSeek
sections survive, conflicting non-critical sections fall back individually,
critical sections (executive_summary / formal_conclusions /
portfolio_risk_analysis) still quarantine the whole brief.

## 37. wrong cash/gross recurrence count

0 unmarked: numeric conflicts are caught by AIBriefFactsV3 program-computed
facts + grounding validators (cash/gross/action count/symbols).

## 38. unknown evidence reference count

0 in ROUND26-generated artifacts.

## 39. official macro news rows

60 (live Federal Reserve RSS + US Treasury RSS + BLS public API v2).

## 40. general market news rows

0 (GENERAL_MARKET_NEWS_UNAVAILABLE; no fabricated news).

## 41. news clusters

58.

## 42. pre-decision news rows

Not materialized as decision evidence (classification available per row via
published_at vs decision cutoff).

## 43. post-decision/pre-execution rows

Classification machinery live; latest pre-execution check CLEAR.

## 44. fabricated news count

0 (no model-generated news persisted; BLS items with unknown release dates are
marked PUBLICATION_DATE_UNAVAILABLE_AVAILABLE_AT_RETRIEVAL).

## 45. Pre-execution result

PRE_EXECUTION_CLEAR (overnight news / market gap / freshness / halts).

## 46. partial fill support

Yes: ManualExecutionOrder → N ManualExecutionFill with cumulative cap and
explicit override; `python main.py execution` wizard.

## 47. reconcile support

Yes: `python main.py portfolio-reconcile <csv>` (PREVIEW default, --commit
applies; immutable snapshot retained).

## 48. live ledger status

Real ledger only source of holdings; target never mutates positions
(invariant-tested).

## 49. live track record days

NO_LIVE_TRACK_RECORD (no real fills yet; performance machinery ready).

## 50. SPY comparison availability

Benchmark evidence per run (decision-time period return/vol); no live track
record yet.

## 51. QQQ comparison availability

Same as SPY.

## 52. research certification

NOT_CERTIFIABLE (unchanged; provisional forward operation remains explicitly
separate).

## 53. StrategyApproval

EFFECTIVE `strategy-approval-bfbae9463078b2fa` ALLOW_PROVISIONAL_FORWARD
(frozen Classical Champion USAdaptiveAlphaCoreV1:1.0.0:427671e52a53).

## 54. OperationalPolicy

EFFECTIVE `operational-policy-527ff899eb81ae2d248e` ALLOW_PROVISIONAL
(expires 2026-08-21).

## 55. DATA runtime

178.8s (latest; ≤180s budget).

## 56. total quant runtime

267.8s total (AI external 83.2s reported separately).

## 57. AI runtime

83.2s (4 DeepSeek calls).

## 58. DB query regression

None: ROUND25 batch paths retained; new forward/exposure code uses batch
queries; query-count regression tests green.

## 59. full pytest

1160 passed, 0 failed (the 2 ROUND23 baseline failures are fixed at root cause).

## 60. quant-critical

31 passed.

## 61. Ruff

Clean.

## 62. Mypy

`mypy --strict`: no issues in 464 source files.

## 63. secret scan

SECRET_SCAN_PASS.

## 64. git status

Clean at report time.

## 65. commits

e335b75 decision manifest / replay / drift / UNKNOWN fix / round23 root-cause ·
a7a774c forward probability evidence ledger ·
daa870b current size/sector exposure + AIBriefFactsV3 + section quarantine ·
e417f8b official macro news acquisition ·
8d438e5 universe invariant tests + quality closure ·
1737b04 grounding ticker word-boundary fix.

## 66. remaining blockers

- Historical research remains NOT_CERTIFIABLE (permanent this round).
- Size/sector current coverage is 0%: no verifiable market-cap / issuer-SIC
  feed for the full universe is available; statuses are honestly DEGRADED.
- General-market news API unconfigured (GENERAL_MARKET_NEWS_UNAVAILABLE).
- Live DeepSeek PASS4 output occasionally fails strict schema and falls back
  to the deterministic brief (fail-closed; formal decisions unaffected).
- No live track record yet (no real fills executed).
- BEA/SEC macro endpoints not wired (BEA needs a key; SEC EDGAR remains on the
  separate PIT-gated path).
