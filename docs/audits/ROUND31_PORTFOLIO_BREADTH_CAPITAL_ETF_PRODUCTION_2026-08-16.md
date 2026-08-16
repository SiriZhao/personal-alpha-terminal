# ROUND31 — Portfolio Breadth / Capital Utilization / ETF Actionability / OOS Strategy Selection

## Verdict

`ROUND31_FINAL_STATUS = PASS`

`FINAL_VERDICT = ROUND31_KEEP_CURRENT_POLICY_FORWARD_EVIDENCE_REQUIRED`

ROUND31 does not change the production portfolio optimizer and does not
introduce a fixed cardinality cap. The current policy remains
`OPTIMIZER_DECIDED`, with no fixed holdings cap and all 1,171 eligible
candidates entering the optimizer.

## 1. Why no policy change

There is no certified historical OOS backtest and no mature synchronized
Portfolio/SPY/QQQ forward outcome sample. Any annualized or risk-adjusted claim
from such a sample is forbidden. The ROUND31 fixture comparison exercises
cardinality, cost, turnover, and risk mechanics but is explicitly
`FIXTURE_OOS_STYLE_WALK_FORWARD_NOT_CERTIFIED`; it cannot outrank the current
production optimizer.

## 2. Breadth comparison

`reports/validation-artifacts/portfolio_breadth_audit.json` compares the same
deterministic fixture universe under identical calendar, benchmark, cost, and
monthly next-session-open rebalance assumptions.

| Policy | Net return | CAGR | SPY rel | QQQ rel | Sharpe | Sortino | Max DD | Vol | Turnover | Cost USD | Win rate | Alpha decay |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 272.63% | 274.59% | 261.78% | 267.28% | 12.80 | 56.30 | -0.85% | 10.38% | 3.34 | 4,956.28 | 100% | 1.93 |
| 15 | 228.31% | 229.87% | 217.46% | 222.96% | 11.93 | 46.18 | -1.00% | 10.07% | 3.43 | 4,689.33 | 100% | 1.97 |
| 20 | 197.56% | 198.86% | 186.71% | 192.21% | 11.22 | 40.25 | -1.13% | 9.83% | 3.18 | 3,987.04 | 100% | 1.91 |
| 25 | 180.59% | 181.74% | 169.73% | 175.23% | 10.86 | 37.46 | -1.13% | 9.60% | 2.58 | 3,156.59 | 100% | 1.82 |
| 30 | 162.92% | 163.94% | 152.07% | 157.57% | 10.27 | 32.89 | -1.17% | 9.51% | 2.55 | 2,917.93 | 100% | 1.80 |
| 40 | 134.78% | 135.58% | 123.93% | 129.43% | 9.19 | 26.54 | -1.36% | 9.39% | 1.97 | 2,043.92 | 100% | 1.68 |
| VARIABLE | 180.59% | 181.74% | 169.73% | 175.23% | 10.86 | 37.46 | -1.13% | 9.60% | 2.58 | 3,156.59 | 100% | 1.82 |
| OPTIMIZER_DECIDED | NOT_AVAILABLE | NOT_AVAILABLE | NOT_AVAILABLE | NOT_AVAILABLE | NOT_AVAILABLE | NOT_AVAILABLE | NOT_AVAILABLE | 7.60% | NOT_AVAILABLE | NOT_AVAILABLE | NOT_AVAILABLE | NOT_AVAILABLE |

These rows are synthetic and not production evidence. They do show that more
holdings reduce fixture turnover and cost but also reduce synthetic return; no
decision is made from them.

## 3. Avoid Top-N regression

The production path is unchanged:

- Optimizer input: `1171`
- Pre-optimizer Top-N truncation: `null`
- Fixed holdings cap: `null`
- Final formal actions: `10`

The fixture strategy is labelled `FIXTURE_POST_SIGNAL_CARDINALITY_PROJECTION`
with `production_authority=NONE`. It is not a production Top-N optimizer.

## 4. Gross / cash diagnosis

`reports/validation-artifacts/risk_budget_counterfactual.json` confirms the
current result is a risk-model result, not a bug:

- Production: gross `27.23%`, cash `72.77%`, expected vol `7.60%`, target vol
  `15%`
- Target volatility is an upper bound, not a leverage target.
- Fixture current and risk-budget loosening variants remain at ~30% gross
  because the small fixture constraints are not binding; this does not imply the
  production 1,171-asset optimizer would behave identically.

The audit does not recommend raising gross from fixture evidence.

## 5. ETF actionability

`reports/validation-artifacts/etf_actionability_audit.json`:

- ETF formal actions: `0`
- ETF research observations: `55`
- All research targets are non-executable
- All research targets carry `NONE` / `RESEARCH_ONLY` trading permission
- No ETF research row enters the formal action list or execution plan

If ETFs are later admitted to production, they must use the unified
`DATA -> PIT -> FACTOR/SIGNAL -> PORTFOLIO -> RISK -> DECISION -> EXECUTION`
chain and appear in the same formal action list.

## 6. Forward performance

`reports/validation-artifacts/forward_performance_audit.json`:

- Status: `SAMPLE_INSUFFICIENT`
- Portfolio observations: `0`
- SPY observations: `0`
- QQQ observations: `0`
- Forward prediction rows: `264`
- Mature outcome rows: `0`

No CAGR, Sharpe, drawdown, alpha, turnover, cost, slippage, or hit rate is
claimed from real forward records.

## 7. Recommendation

`reports/validation-artifacts/round31_policy_recommendation.json`:

- Recommended policy: `OPTIMIZER_DECIDED`
- Decision: `KEEP_CURRENT_POLICY`
- Status: `ROUND31_KEEP_CURRENT_POLICY_FORWARD_EVIDENCE_REQUIRED`

No fixed 10/15/20/25/30/40 or variable cardinality policy is promoted.

## 8. Test results

- full pytest: `1217 passed`
- quant-critical: `31 passed`
- quant regression: `317 passed`
- walk-forward / PIT / leakage / cost / optimizer / cardinality / ETF / TUI:
  `66 passed`
- ROUND31 targeted: `6 passed`
- CURRENT_STATUS + ROUND31: `10 passed`
- ruff: `PASS`
- mypy strict: `PASS (471 source files)`
- secret scan: `SECRET_SCAN_PASS`
- `git diff --check`: `PASS` (LF/CRLF warnings only)

## 9. Artifacts

- `reports/validation-artifacts/portfolio_breadth_audit.json`
- `reports/validation-artifacts/risk_budget_counterfactual.json`
- `reports/validation-artifacts/etf_actionability_audit.json`
- `reports/validation-artifacts/forward_performance_audit.json`
- `reports/validation-artifacts/round31_policy_recommendation.json`
- `reports/validation-artifacts/round31_validation_summary.json`
- `docs/CURRENT_STATUS.json`
- `docs/CURRENT_STATUS.md`

## Final

`ROUND31_FINAL_STATUS = PASS`

`FINAL_VERDICT = ROUND31_KEEP_CURRENT_POLICY_FORWARD_EVIDENCE_REQUIRED`
