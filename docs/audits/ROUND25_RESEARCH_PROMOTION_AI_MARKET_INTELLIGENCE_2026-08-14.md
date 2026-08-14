# ROUND25 — RESEARCH PROMOTION / AI MARKET INTELLIGENCE / ETF SEMANTIC CLOSURE /
# RISK-ADJUSTED ALPHA / EXECUTION LEDGER / PERFORMANCE RECOVERY

Date: 2026-08-14 (Asia/Shanghai)
Branch: `codex/round25etf`
Baseline frozen at: `var/backups/round25-baseline-2026-08-14/` (git HEAD `232693c`)
ROUND24 baseline certificate: `daily-fdfdb74f281647399300f5398f74674b`

## 1. ROUND25 verdict

`ROUND25_READY_RESEARCH_NOT_PROMOTED`

Semantic correctness, AI intelligence, market-state, news pipeline, pre-execution
risk layer, performance recovery and execution-ledger UX are complete.  No new
model (Regime, Drawdown Governor, ETF sleeves, Alpha challengers) accumulated
enough certified history to be promoted; nothing was promoted automatically.

## 2. Current actionable pipeline status

Latest gate run: `daily-b44f9df483d240cfb5f25f015592c747`
`VALID_ANALYSIS_ACTIONABLE_PROVISIONAL`, Pipeline READY.
Stages: CALENDAR PASS / DATA PASS / PIT PASS / LLM_INTELLIGENCE PASS_DEGRADED /
ETF_SLEEVE PASS / AI_BRIEF PASS_DEGRADED / FEATURE PASS / FACTOR PASS /
SIGNAL PASS / PROBABILITY PASS_DEGRADED / PORTFOLIO PASS / RISK PASS /
DECISION PASS / EXECUTION PASS / PERSISTENCE PASS / PRE_EXECUTION CLEAR.
Operational authorization = ALLOW_PROVISIONAL; signal = PASS_PROVISIONAL;
automatic execution DISABLED / MANUAL_ONLY; Broker API DISABLED.

## 3. Formal equity actions

9 STOCK BUY (identical symbol set to the ROUND24 baseline):
ATEX, CNC, LQDA, RLAY, RVMD, STX, TVTX, UMC, VSTS (EQUITY_ALPHA sleeve).
Target-weight deltas vs baseline ≤ 4.8e-6 (SLSQP tolerance); quantities identical.

## 4. Formal ETF actions

None. Zero ETF rows pass the formal chain (SIGNAL→PORTFOLIO→RISK→DECISION→EXECUTION).

## 5. ETF research candidates

ETF_CORE: IVV, VOO, VTI (+ IJR/IUSV/IVE/VLUE as tactical-style candidates),
ETF_TACTICAL pool of 50; all `RESEARCH_CANDIDATE`, trading permission NONE.

## 6. Any research candidate leaked into execution?

No. Renderer isolated: formal table renders only FORMAL_ACTIONABLE rows;
ETF targets render under 【研究候选 · 不执行】 with NONE permission.
Semantic-domain tests enforce this (`test_round25_semantic_domains`,
`test_round25_renderer_semantic_isolation`).

## 7. ETF "Alpha >100%" root cause

The ETF sleeve `expected_value` was `risk_adjusted_momentum` =
`momentum_252_21 (decimal cumulative return) / volatility_63 (annualized vol)`
— a dimensionless ratio such as 1.25 — rendered under a column named "Alpha"
with implicit ×100 → "+125.03%".  Root cause: field mislabeled as expected
return and unit-implicit renderer.

## 8. Corrected ETF metric semantics

Renamed to `momentum_vol_ratio` with `ETF_METRIC_SEMANTIC_CONTRACT` units
(PERCENT / DECIMAL_RETURN / ZSCORE / RANK / RAW_PRICE_RETURN /
ANNUALIZED_RETURN / RATIO).  Renderer shows 12M动量 (percent, from
momentum_252_21) and 动量/波动比 (plain ratio) separately; never labeled Alpha;
NaN/Inf/extreme values surfaced unclamped.

## 9. AI brief status

DailyAIBriefV2 (`ai-brief-zh-v2`) implemented and running every daily run.
Real DeepSeek multi-pass output produced (`DEEPSEEK_MULTIPASS_JSON`,
`daily-03fed...`); later runs were quarantined by the semantic-grounding
validator with the safe deterministic v2 fallback displayed, marked
(`AI_BRIEF_QUARANTINED_SEMANTIC_MISMATCH`).

## 10. AI full terminal status

Full 19-section brief is the default terminal view (no `--full` needed);
`--compact`-style truncation removed from the default path.

## 11. AI formal/research grounding status

`AI_SEMANTIC_GROUNDING_VALIDATOR` active. It detects research-candidate-as-holding,
research-candidate-as-executable, context-as-target, formal omission, wrong
action count, wrong cash and wrong formal gross; quarantines on any issue.

## 12. Market-state status

`MARKET_STATE_SNAPSHOT` implemented from verified local price bars
(SPY/QQQ/IWM/VOO/VTI + 11 sector ETFs + TLT/IEF/GLD; breadth across 5025
symbols via one windowed SQL). QUANT_FACT boundary: LLM may only interpret.

## 13. News provider status

`MARKET_NEWS_INTELLIGENCE` implemented. No general news API configured:
`GENERAL_MARKET_NEWS_UNAVAILABLE` (no fabricated news).

## 14. Official macro provider status

`OfficialMacroNewsProvider` interface present (Fed/BLS/BEA/Treasury target);
acquisition disabled in this environment (no network-enabled run).

## 15. General news provider status

Pluggable `GeneralMarketNewsProvider` adapter; unavailable without configuration.

## 16. News rows

0 (honest empty ledger).

## 17. News clusters

0.

## 18. Pre-decision news rows

0.

## 19. Post-decision/pre-execution news rows

0.

## 20. DeepSeek calls

4 per daily run (PASS1 facts / PASS2 risk critic / PASS3 market-news synthesis /
PASS4 final brief).

## 21. Prompt tokens

Accumulated per run (recorded in ai_brief.json `llm_calls`); cost explicitly
not a constraint this round.

## 22. Completion tokens

Recorded per run in `llm_calls`.

## 23. LLM latency

Recorded per run; AI_BRIEF stage ≈ 49–67s (4 network calls).

## 24. LLM production influence

NONE (trade/target-weight/BUY/SELL authority NONE).

## 25. Probability production influence

0 (PROBABILITY_FALLBACK_CLASSICAL; production weight 0).

## 26. Regime state

`MARKET_REGIME_ENGINE_V1` remains RESEARCH_ONLY; no calibrated probability
evidence was available at the decision cutoff.

## 27. Regime production influence

NONE.

## 28. Drawdown governor research result

Stress Exam 2.1 (scenario params unchanged): variant C (gross ×0.85) worst
BROAD_EQUITY_CRASH maxDD −23.2% vs champion −26.8%; research only.

## 29. ETF Core experiment

Equity+ETF_CORE: net 42.7%, Sharpe 1.16, maxDD −19.3% on the 505-session
common window vs baseline SPY net 49.9%, Sharpe 1.29, maxDD −19.0%.
Lower return/Sharpe; no diversification win on this window.

## 30. ETF Tactical experiment

Equity+ETF_TACTICAL: net 42.9%, Sharpe 1.18, maxDD −18.8%.

## 31. Best ETF experiment

None beat the equity-only baseline on net/Sharpe on the available window;
all labeled LIMITED_EVIDENCE_RESEARCH / INSUFFICIENT_CERTIFIED_HISTORY.

## 32. Alpha challengers evaluated

Candidates registered: residual momentum, volatility-managed momentum, trend
strength, short-term reversal, idiosyncratic volatility, liquidity factor,
cross-sectional breadth, relative strength. None completed a certified
locked-OOS run this round (see 60).

## 33. Best Alpha challenger

None promoted.

## 34. Factor correlation

Classical factor set unchanged (quality-constrained medium-term momentum
`427671e52a53`). ETF sleeve overlap reported via correlation clustering
(e.g., IVV/VOO ≈ 0.997) with look-through UNAVAILABLE.

## 35. After-cost result

Formal plan after cost: 9 buys, estimated cost $18.96, turnover 27.68%,
cash after ≈ $72,302.52.

## 36. SPY comparison

Benchmark evidence: SPY period return 28.61%, annualized vol 17.80%
(decision-time evidence). No live strategy track record exists; comparisons
are evidence-only.

## 37. QQQ comparison

QQQ period return 38.32%, annualized vol 23.11%.

## 38. Max drawdown

Stress worst scenario (champion): BROAD_EQUITY_CRASH −26.75% (synthetic).

## 39. CVaR

Per-scenario CVaR 95% recorded in stress_exam_v2_1_comparison.json.

## 40. Stress worst scenario

BROAD_EQUITY_CRASH (−26.75% champion).

## 41. BROAD_EQUITY_CRASH before/after

Champion −26.75% → regime variant −19.46% → drawdown-governor −23.18% →
ETF-core −40.7% (ETF variant loses concentration diversification in a uniform
crash on this synthetic path).

## 42. CORRELATION shock before/after

Champion CORRELATION_TO_ONE −4.4%; variants recorded in the comparison
artifact (research only).

## 43. LIQUIDITY shock before/after

Champion LIQUIDITY_COLLAPSE −22.9%; ETF-core worst −43.3% (liquidity decay
compounds on the diversified sleeve in this scenario family).

## 44. Size exposure status

`SIZE_EXPOSURE_UNAVAILABLE` / `CURRENT_SIZE_DIAGNOSTIC` only. Historical PIT
market-cap data remains unavailable; current data is never used for
historical neutralization.

## 45. Sector exposure status

`SECTOR_EXPOSURE_NOT_VALIDATED` (industry linkage coverage ≈ 0 in the
security master). Missing data is never treated as safe.

## 46. ETF look-through status

`ETF_LOOKTHROUGH_UNAVAILABLE`; overlap via return-correlation clustering only.

## 47. Partial fills status

Supported: `ManualExecutionOrder` → N `ManualExecutionFill`
(PENDING/PARTIAL/FILLED/CANCELLED); cumulative fills may not exceed approved
quantity without an explicit override + audit reason; interactive
`python main.py execution` wizard added.

## 48. Portfolio reconciliation status

`python main.py portfolio-reconcile <csv>` — PREVIEW by default, `--commit`
applies the broker snapshot; immutable reconciliation snapshots retained.

## 49. Cost-learning status

`REALIZED_EXECUTION_COST_OBSERVATION` research active via
`python main.py execution-costs`; production cost model never auto-updated;
sufficient samples only emit `COST_MODEL_RECALIBRATION_CANDIDATE` for human
approval (0 observations today).

## 50. Previous runtime

ROUND24 trace: total 980.36s, DATA 877.89s.

## 51. ROUND25 runtime

Latest gate run: total 237.4s (AI/LLM external 64.8s reported separately).

## 52. DATA runtime

166.9s (quant/data core; convention attributes the quant core to DATA).
Budget ≤ 180s met.

## 53. DB query count

N+1 eliminated: universe selection dropped ~10k per-symbol roundtrips
(calendar + PIT version), price bounds collapsed to one GROUP BY;
query-count regression tests added.

## 54. provider calls

Latest manifest: requested 5027, refreshed 70 (incremental), provider
success 1.0, cache reused 4238 / historical 4957.

## 55. cache reused

4238 (current cache) + 4957 (historical cache) per latest manifest.

## 56. latest-price coverage

0.857 (latest-price coverage of the 5027-symbol universe).

## 57. fixed holdings cap

None (NO_FIXED_CARDINALITY_CAP preserved).

## 58. pre-optimizer Top-N

None (no pre-optimizer Top-N truncation).

## 59. optimizer cardinality cap

None (optimizer receives the full eligible alpha set).

## 60. Research certification

`NOT_CERTIFIABLE` unchanged. All ROUND25 research is
`LIMITED_EVIDENCE_RESEARCH` / `INSUFFICIENT_CERTIFIED_HISTORY` /
`FORWARD_RESEARCH_CANDIDATE`. Never called CERTIFIED_ALPHA.

## 61. StrategyApproval status

EFFECTIVE: `strategy-approval-bfbae9463078b2fa`, ALLOW_PROVISIONAL_FORWARD,
frozen Classical Champion USAdaptiveAlphaCoreV1:1.0.0:427671e52a53.

## 62. OperationalPolicy status

VALID/EFFECTIVE: `operational-policy-527ff899eb81ae2d248e`,
ALLOW_PROVISIONAL, expires 2026-08-21.

## 63. full pytest

1128 passed, 2 failed — both failures are pre-existing on the ROUND24
baseline (`test_round23_daily_performance_forward_authorization.py`, verified
via stash on HEAD before any ROUND25 change).

## 64. quant-critical

31 passed.

## 65. Ruff

Clean (src + tests).

## 66. Mypy

`mypy --strict`: no issues in 457 source files.

## 67. secret scan

`SECRET_SCAN_PASS`.

## 68. git status

Clean at report time (9 ROUND25 commits on top of ROUND24 baseline
`232693c`; branch `codex/round25etf`).

## 69. commits

90949e7 P0 semantic isolation + ETF metric contract ·
af916a7 market-state / news / pre-execution / AI brief v2 ·
c11427d N+1 elimination + DATA profiler ·
a1ef849 execution wizard / reconcile / cost learning ·
82edb27 research labs + experiment registry ·
933f2d2 exposure closure / terminal IA / stress exam 2.1 ·
82ea80c quality gates (ruff/mypy) ·
a847c49 optimizer 5x speedup ·
abd1682 optimizer fast-path gated to large universes.

## 70. remaining blockers

- Historical research remains NOT_CERTIFIABLE (unchanged, permanent this round).
- 2 pre-existing ROUND23 approval unit tests fail on the baseline (documented,
  not introduced by ROUND25).
- Official-macro / general-market news acquisition needs a network-enabled
  run or a configured news API; until then news stays UNAVAILABLE honestly.
- ETF constituent look-through needs a stable, verifiable weights source;
  correlation clustering remains the fallback.
- Real DeepSeek multi-pass brief occasionally quarantined by the semantic
  grounding validator (fail-closed behavior; deterministic fallback shown).
