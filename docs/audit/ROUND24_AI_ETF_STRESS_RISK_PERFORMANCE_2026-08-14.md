# ROUND24 AI Chinese Advisory / ETF Multi-Sleeve Universe / Stress & Risk 2.0 / Daily Performance Closure

Date: 2026-08-14

Verdict: `ROUND24_READY_RESEARCH_CANDIDATES_NOT_PROMOTED`

## 1. ROUND24 verdict

ROUND24_READY_RESEARCH_CANDIDATES_NOT_PROMOTED.

All required features are operational and every quality gate passes:

- ETF multi-sleeve universe operational; VOO / QQQ handled correctly with
  separated BENCHMARK + TRADABLE roles.
- AI Chinese advisory brief operational (live DeepSeek JSON, schema-validated,
  cached, quarantined on failure).
- AI authority remains bounded: trade / target-weight / BUY-SELL authority
  all NONE; production influence NONE.
- Stress Exam 2.0 complete: production-coupled baseline, 22 market scenarios,
  12 resilience scenarios, ten-axis scorecard, critical failures never masked.
- Risk invariants preserved: Classical Champion unchanged, no risk gate
  relaxed, manual-only, broker API disabled.
- Performance materially improved: live full run ~193 s (was ~2513 s);
  717 structurally-insufficient-history symbols no longer re-requested daily.
- No future leakage, no survivorship claim inflation.

No new Alpha/Risk/ETF model was promoted.  This is the legal and more
credible outcome; nothing was force-promoted.

## 2. Stock universe count

Broad current universe 5027 registered US symbols; certified current
operational universe 2133 (run daily-121428207ec841159c839a1c110b0435).

## 3. ETF universe count

- raw listed ETFs in the Nasdaq symbol directory: 1387
- catalog known (deterministic curated catalog): 67
- ETF core eligible: 6 (VOO, QQQ, QQQM, SPY, VTI, IVV)
- ETF tactical eligible: 50
- blocked complex products: 11 (TQQQ, SQQQ, UPRO, SPXU, SSO, SDS, UDOW,
  SOXL, SOXS, UVXY, VXX)
- unclassified ETFs (RESEARCH_ONLY, fail-closed): 1320

## 4. VOO status

PASS.  In universe; 501 DB bars; PIT contract PASS; tradable ETF
(ETF_CORE_SLEEVE); benchmark_role BOTH; benchmark policy
BENCHMARK_UNAVAILABLE_SELF (no self-comparison).  Live ETF sleeve target
0.0707 at research-candidate status.

## 5. QQQ status

PASS.  In universe; 506 DB bars; PIT contract PASS; tradable ETF
(ETF_CORE_SLEEVE); benchmark_role BOTH (same security_id, roles separated;
no benchmark/tradable identity collision).

## 6. Equity factor eligible

2133 cross-sectional observations in the live run; factor eligible
follows the existing CURRENT_OPERATIONAL_PIT funnel unchanged.

## 7. ETF factor eligible

Price-only ETF factor engine (`etf-price-factors-v1`): 55 factor snapshots
in the live run (6 core + 50 tactical eligible, minus benchmark).  Company
fundamental factors are never applied to ETFs.

## 8. Final equity targets

SIGNAL stage is FAIL_BLOCKING in the post-ROUND24 runs because the
StrategyApproval identity no longer matches the changed config
(REAUTHORIZATION_REQUIRED).  The last actionable equity targets remain the
frozen baseline: ATEX, CNC, LQDA, RLAY, RVMD, STX, TVTX, UMC, VSTS
(baseline run daily-e1a61f374f104bcfac2ba5ae39567c56).

## 9. Final ETF targets (live, research candidates)

- ETF_CORE: IVV 0.0704, VOO 0.0707, VTI 0.0704, QQQM 0.0385
- ETF_TACTICAL: IVE 0.0347, IUSV 0.0341, IJR 0.0201, VLUE 0.0110
- All labeled RESEARCH_CANDIDATE; none auto-executed.

## 10. LLM Chinese Brief status

OPERATIONAL.  Live run generated a real DeepSeek brief
(source DEEPSEEK_JSON, schema ai-brief-zh-v1, validation PASS,
latency ~8.9 s, prompt_tokens 10733, completion_tokens 639).
Terminal shows 【AI 中文研判】 compact view; `python main.py intelligence
brief --full` renders the full Chinese brief; `python main.py explain
<SYMBOL>` appends the AI 中文解读 section.  Failure paths degrade to
RULE_BASED_DETERMINISTIC with LLM PASS_DEGRADED; malformed payloads are
quarantined (AI_BRIEF_QUARANTINED) and never pollute the production run.

## 11. DeepSeek calls / cost

One brief call per (run_id + data/factor/portfolio/risk/intelligence hash +
model + prompt_version); cached afterwards.  Live cost fields come from the
provider usage block (estimate recorded in the ai_brief.json artifact;
DeepSeek v4 flash pricing).

## 12. LLM production influence

NONE.  LLM trade authority NONE, target-weight authority NONE, BUY/SELL
authority NONE.  LLM mode SHADOW.

## 13. Probability production weight

0.  PROBABILITY_FALLBACK_CLASSICAL remains the production mode.

## 14. Stress Exam v2 score

`STRESS_EXAM_V2_PASS`, baseline OK (production run daily-e1a61f holdings).
Scorecard: DATA 100, PIT 100, ALPHA 0, PORTFOLIO 50, RISK 50, ETF 50,
LLM 100, PROBABILITY 100, OPERATIONS 100, RESILIENCE 100.

PORTFOLIO/RISK 50 reflects honest gate violations in market scenarios
(not masked by the total).  ALPHA 0 is correct: the exam is not alpha
certification.  ETF 50: the production baseline currently holds no ETF
sleeve positions.

## 15. Max drawdown by scenario

Worst: BROAD_EQUITY_CRASH maxDD -35.9% (CVaR 1.84%).  Other notable:
FAST_CRASH_GAP -10.3%; SECTOR_CRASH -13.4%; CORRELATION_TO_ONE -11.6%;
LIQUIDITY_COLLAPSE -11.1%; VOLUME_COLLAPSE -18.1%;
SINGLE_NAME_MINUS_80 -6.1%; SLOW_BEAR_MARKET -20%+ region.

## 16. Worst scenario

BROAD_EQUITY_CRASH (maxDD -35.94%).

## 17. Sector crash result

maxDD -13.4%; no gate violation at current sector exposure (the baseline
has no validated stock sector metadata -> SECTOR_EXPOSURE_NOT_VALIDATED is
reported, never a fake "safe" label).

## 18. Correlation shock result

maxDD -11.6%; `maximum_correlation_spike_loss` gate violation recorded
honestly (correlation -> 1 removes diversification).

## 19. Liquidity shock result

maxDD -11.1%; liquidation-day gate still satisfied by the liquid baseline.

## 20. Provider outage result

Live probe not injected (NOT_INJECTED in live exam; unit-tested with fault
injection: provider outage -> fail-closed partial status, no fabricated
bars).  Live probes executed: MISSING_BARS / STALE_BARS / DUPLICATE_BARS /
FUTURE_ROW_INJECTION / DEEPSEEK_TIMEOUT / DEEPSEEK_MALFORMED_RESPONSE /
PROBABILITY_UNAVAILABLE, all PASS.

## 21. Size neutralization status

DEGRADED (unchanged by design).  Root cause: the deterministic security
master has no PIT market-cap source; `metadata_frame` market_cap is
unavailable, so size scores stay empty and the risk model reports
SIZE_EXPOSURE_DEGRADED.  Per ROUND24 D11 the warning is preserved, not
removed.  Adding a PIT market-cap provider is future work (TECH_DEBT).

## 22. Regime engine status

MARKET_REGIME_ENGINE_V1 built and RESEARCH_ONLY.  Live computation:
RISK_ON, score 2.36 (SPY>MA200, breadth 57.8%, realized vol 13.8%).
It never feeds the production risk budget; the production chain keeps
REGIME_OPTIONAL_UNAVAILABLE until a walk-forward calibrated regime exists.

## 23. Risk overlay promotion candidate

Drawdown governor v1 produced as `RISK_OVERLAY_PROMOTION_CANDIDATE`
(research-only, hysteresis-guarded).  It is NOT auto-enabled and changes
no production risk limits.  Dynamic risk budget remains research-only.

## 24. Alpha research candidates

13 candidates registered (residual momentum, volatility-managed momentum,
trend strength, short-term reversal, idiosyncratic volatility, liquidity,
cross-sectional breadth, relative strength + value/quality/profitability/
earnings revision/fundamental growth BLOCKED_BY_PIT_FUNDAMENTALS).
Vol-managed momentum A/B on 2215 symbols: rank correlation 0.928 vs plain
momentum -> NEEDS_WALK_FORWARD_EVIDENCE; no promotion.

## 25. Full backfill count before / after

Before: 717 symbols full-backfilled every daily run.
After: `full_backfill_requested_count = 0`;
`new_listing_waiting_count = 717` (NEW_LISTING_WAITING_FOR_HISTORY with
`history_eligible_after`; no repeated provider requests).
New planner states: FULL_BACKFILL_REQUIRED, STRUCTURALLY_INSUFFICIENT_HISTORY,
NEW_LISTING_WAITING_FOR_HISTORY, PERMANENT_PROVIDER_NO_HISTORY, RETRY_AFTER,
QUARANTINED (sidecar state file: data/cache/broad-universe/backfill_state.json).

## 26. Total daily runtime

~193 s live full run (daily-c9d601d292ec4638a521d248ae85c33c); ~94 s with
--no-refresh.  Performance target (<= 5 min) met without shrinking the
universe, without Top-N, and without skipping PIT/ETF/risk.

## 27-31. Stage runtimes (live run)

- DATA 78.2 s
- Provider: 73 requested, 71 returned, success rate 97.3%
- PIT 0.0 s (incremental)
- Factor/Signal/Portfolio/Risk 0.0 s in the blocked run (SIGNAL
  FAIL_BLOCKING; see #8); ETF_SLEEVE 3.86 s; AI_BRIEF 10.9 s.

## 32. fixed holdings cap

NONE (unchanged).

## 33. automatic execution

DISABLED / MANUAL_ONLY.

## 34. broker API

DISABLED; no Schwab or any trading API added.

## 35. research certification

NOT_CERTIFIABLE / RESEARCH_LIMITED_SURVIVORSHIP (unchanged; not faked).

## 36. strategy approval

Existing StrategyApproval (strategy-approval-1f271580e1fd3c4e,
ALLOW_PROVISIONAL_FORWARD) is now IDENTITY_MISMATCH against the changed
config fingerprint — expected per PHASE M.
**REAUTHORIZATION_REQUIRED**: the operator must explicitly re-run
`python main.py strategy-approval create ...` after reviewing this round.

## 37. OperationalPolicy

Existing policy operational-policy-541e2efd88fe9b7c7825 remains stored;
identity mismatch likewise expected.
**REAUTHORIZATION_REQUIRED**: operator must re-run
`python main.py operational-policy create ...` after code freeze.
Nothing was auto-renewed.

## 38. full pytest

1052 passed (963 unit + 89 integration; ROUND24 added 11 test modules).

## 39. quant-critical

31 passed (governed minimum satisfied).

## 40. Ruff

PASS (E/F/I/B/UP, line-length 100).

## 41. Mypy

Strict mypy PASS over 447 source files.

## 42. Secret scan

SECRET_SCAN_PASS.

## 43. git status

Working tree clean except the ROUND24 changeset (committed at end of round;
see commit below).  ROUND24 work was done on branch
`codex/round24-ai-etf-stress-risk` from baseline c99a20b.

## 44. commits

Baseline freeze commit c99a20b (ROUND21-23 preservation) + the ROUND24
commit (see git log).  No push, no tag, no release.

## 45. remaining blockers

1. REAUTHORIZATION_REQUIRED: StrategyApproval + OperationalPolicy identity
   mismatch after ROUND24 config/code changes (operator action required).
2. Size neutralization remains DEGRADED (no PIT market-cap source).
3. ETF look-through UNAVAILABLE: overlap risk is correlation-based only;
   constituent holdings data is not available.
4. Regime engine v1, drawdown governor, vol-managed momentum are
   RESEARCH_ONLY / promotion candidates; no walk-forward proof yet.
5. DeepSeek brief is advisory only; one LLM call per unique run identity.
6. Historical research certification remains NOT_CERTIFIABLE (correct).

## Prohibited items verification (PHASE P)

None violated: no auto orders, no broker API, no policy auto-renewal, no
scenario difficulty gaming (v2 uses the production portfolio, harder not
easier), no return-tuning, no future/survivorship leakage, current universe
never presented as historical, LLM has no BUY/SELL/weight authority,
Probability stays weight 0, ETFs never receive company fundamentals,
leveraged/inverse blocked by default, holdings cap/Top-N stay removed,
no universe shrinkage for performance, no risk-gate relaxation, no faked
historical certification.
