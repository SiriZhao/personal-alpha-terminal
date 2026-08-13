# ROUND 11 - Probability-to-Portfolio & LLM Runtime Closure

Date: 2026-08-13
Branch: `codex/round11-probability-portfolio-llm-closure`
Final live run: `daily-e5a547a5eba1449c80aea9f1f5919c9b`

## Verdict

`ROUND11_BLOCKED_PRODUCTION_APPROVAL`

The implementation and quality gates pass, but the complete production acceptance does
not pass. The final live run correctly stopped at `SIGNAL` because no immutable strategy
approval backed by locked OOS, PIT, survivorship-controlled, after-cost evidence exists.
`PORTFOLIO`, `RISK`, and `DECISION` therefore did not run. No approval or user policy was
created or altered to bypass this gate.

Probability is no longer empty because of `PROBABILITY_ARTIFACT_MISSING`. A deterministic,
immutable assessment is loaded from real ROUND 4 evidence. Its honest verdict is
`NO_INCREMENTAL_ALPHA`, so production influence remains `0.0` and the daily path reports
`PROBABILITY_FALLBACK_CLASSICAL:NO_INCREMENTAL_ALPHA`.

## Probability Assessment

Artifact ID: `round4-probability-ae27b79d1a3585497ab2`
Artifact hash: `29c4897f25b79050a7b0dfd13cc69abcd42dd708cb2421e9c0b29d34857ab2eb`
Model: `Round4LogisticCalibrationV1`
Strategy: `USAdaptiveAlphaCoreV1` version `1.0.0`
Data version: `16dad3190df4450b5cd72dcfb91e9d254ff164209cbcb74d44ce9a23f28744ef`
Feature fingerprint: `ad07b45f89b660d5b5cfa093f81ff83e16a51c3aeddc4416eb6935fe2ee7ee70`

Windows:

- Training: 2024-08-30 through 2025-09-04
- Validation: 2025-10-03 through 2026-03-06
- Locked OOS: 2026-04-07 through 2026-08-06
- Walk-forward rebalance dates: 24
- PIT convention: features and outcomes available no later than each decision cutoff
- Outcome: 21-session forward return relative to SPY after configured transaction costs

Observed calibration and discrimination:

| Metric | Probability | Reference |
|---|---:|---:|
| Brier | 0.244396 | base-rate Brier 0.242752 |
| LogLoss | 0.681850 | not available |
| ECE | 0.053211 | not available |
| ROC-AUC | 0.520024 | fixed gate not met |

Observed A/B portfolio evidence:

| Metric | Classical | Classical + Probability |
|---|---:|---:|
| Net return | 0.00017306 | 0.00017306 |
| Sharpe | 10.696952 | 10.696952 |
| Max drawdown | -0.00000427 | -0.00000427 |
| Turnover | 0.0152888 | 0.0152888 |
| Cost | 8.542507 | 8.542507 |
| Target changes | - | 0 |

Sortino, information ratio, SPY alpha, QQQ alpha, slippage attribution, regime
stability, and net CAGR were not established by the source evidence. Historical PIT
remains limited. These are explicit blockers, not imputed results.

## Counterfactual Trace

The terminal and immutable daily snapshot expose the requested fields. In the final run,
`AAOI` demonstrates the fallback behavior:

| Field | Value |
|---|---:|
| base_alpha | 0.02939138 |
| conditional_probability | unavailable |
| probability_reliability | `UNAVAILABLE_FALLBACK` |
| probability_adjusted_alpha | 0.02939138 |
| target_without_probability | 0.0 |
| target_with_probability | 0.0 |
| probability_weight_impact | 0.0 |
| decision_without_probability | `NO_ACTION` |
| final_decision | `NO_ACTION` |
| decision_changed_without_probability | `false` |

`pre_risk_target` and `post_risk_target` are explicitly
`NOT_EXPOSED_BY_ENGINE`. Because `SIGNAL` was blocked, this is a diagnostic
counterfactual and not a claim that portfolio/risk optimization ran.

## Operational Policy

The stored policy was preserved without renewal or replacement:

- Decision: `ALLOW_PROVISIONAL`
- Effective: `false`
- Reason: `OPERATIONAL_POLICY_IDENTITY_MISMATCH`
- Machine-readable degraded reason:
  `OPERATIONAL_POLICY_IDENTITY_MISMATCH; production advice blocked`

The terminal no longer describes this policy as allowing advice. Stored identity,
effective state, and blocking reason are shown separately.

## LLM Runtime

Canonical commands:

```text
python main.py llm status
python main.py llm test
```

Real API acceptance:

- Provider: `deepseek`
- Model: `deepseek-v4-flash`
- Base URL: `https://api.deepseek.com`
- Credential: `PRESENT` (value never rendered or persisted)
- Connectivity: `AVAILABLE`
- Structured JSON: valid
- Final test latency: 1,699 ms
- Production influence: `NONE`

The daily run reads only the sanitized runtime status and performs no extra API call.
Malformed or config-mismatched status files fall back to `NOT_TESTED`. LLM availability
cannot block or modify the Classical Quant Core.

## Universe Funnel

Final live run, analysis date 2026-08-12:

| Stage | Count |
|---|---:|
| Listed securities | 8,835 |
| Listed equities | 7,476 |
| Eligible security type | 4,957 |
| Latest-price covered | 4,953 |
| History sufficient | 4,534 |
| Current PIT eligible | 3,433 |
| Liquidity eligible | 2,128 |
| Factor eligible | 2,128 |
| Alpha positive | 1,165 |
| Candidate pool | 100 |
| Optimizer input | 100 |
| Final holdings | 0 |
| Quarantined | 1 |

The run used `LIVE_REFRESH`, not cache replay. `SVA` returned no price data and remained
isolated. No future row, synthetic bar, or freshness bypass was used.

## Final Daily Run

| Stage | Result |
|---|---|
| DATA | PASS |
| PIT | PASS, no future observations |
| LLM_INTELLIGENCE | PASS_DEGRADED, AVAILABLE, SHADOW, influence NONE |
| FEATURE | PASS, 2,128 rows |
| FACTOR | PASS, 2,128 cross-sectional observations |
| SIGNAL | FAIL_BLOCKING, strategy not production approved |
| PROBABILITY | PASS_DEGRADED, fallback Classical |
| PORTFOLIO | NOT_RUN, blocked by SIGNAL |
| RISK | NOT_RUN, blocked by SIGNAL |
| DECISION | NOT_RUN, blocked by SIGNAL |
| EXECUTION | NOT_RUN |

Classification: `VALID_ANALYSIS_NON_ACTIONABLE`
Automatic execution: `false`
Manual broker workflow: Charles Schwab unchanged
Ledger: unchanged

## Quality Gates

- Full pytest: `901 passed`
- Explicit probability/leakage/counterfactual/performance/quant suite: `40 passed`
- Ruff: PASS
- strict mypy: PASS, 412 source files
- Secret scan: `SECRET_SCAN_PASS`
- Real DeepSeek API test: PASS
- Real broad live daily run: completed fail-closed in 154.01 seconds

## Remaining Work

1. Obtain and register immutable strategy approval evidence meeting the existing locked
   OOS, full historical PIT/survivorship, and after-cost standards.
2. Only then rerun the same live workflow to exercise `SIGNAL -> PORTFOLIO -> RISK ->
   DECISION` without changing approval thresholds.
3. Probability remains Classical fallback until a future assessment establishes complete
   A/B metrics and after-cost OOS incremental value.

No statistical threshold, PIT gate, risk constraint, cost assumption, policy identity,
LLM authority, or execution control was relaxed in ROUND 11.
