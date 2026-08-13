# Personal Alpha Terminal - First Formal Stress Exam

Date: 2026-08-14

Verdict: `STRESS_EXAM_PASS_WITH_WARNINGS`

## Important distinction

This exam is a deterministic synthetic stress test. It is NOT a historical
backtest and it is NOT alpha certification. Synthetic scenario returns do not
claim that the strategy can outperform markets.

## Exam design

- Deterministic seed: 20260814
- Sessions: 252
- Symbols: SPY, QQQ, IWM, VTI, TLT, GLD, AAPL, MSFT
- Portfolio: synthetic equal-weight exam portfolio with 20% cash baseline
- Rebalance: every 21 sessions
- Risk caps: long-only, gross <= 1.0, position <= 0.15, holdings <= 10
- Costs: us-daily-cost-v1 with scenario-specific spread/liquidity multipliers
- No live portfolio, ledger, database, or OperationalPolicy was modified

## Scenarios

| Scenario | Portfolio | Benchmark | Max DD | Ann Vol | Turnover | Cost | Violations |
|---|---:|---:|---:|---:|---:|---:|---:|
| SCENARIO_A | -51.3% | -61.1% | -57.5% | 43.8% | 2.49 | 7.5% | none |
| SCENARIO_B | -47.1% | -57.6% | -52.7% | 29.4% | 2.21 | 4.0% | none |
| SCENARIO_C | -20.7% | -27.4% | -21.8% | 18.4% | 2.08 | 2.5% | none |
| SCENARIO_D | -18.9% | -34.2% | -20.9% | 11.9% | 2.35 | 1.4% | none |
| SCENARIO_E | +5.2% | +17.2% | -15.5% | 11.5% | 2.35 | 1.1% | none |
| SCENARIO_F | +168.3% | +158.7% | -10.9% | 29.3% | 1.63 | 0.5% | none |

No risk cap violation was observed. Gate advisory blocks are recorded as
warnings, not critical failures.

## Additional shocks

Tested deterministically:

- flash crash
- overnight single-name gap
- correlation shock
- volatility shock
- liquidity shock
- spread x5/x10
- corporate-action anomaly / single-name -80%
- factor inversion
- momentum crash
- future timestamp injection check

Authority-bounded:

- LLM outage
- DeepSeek timeout
- hallucination quarantine spike
- Probability unavailable
- Probability miscalibration

Not modeled in this synthetic engine:

- sector crash
- volume collapse
- provider outage
- missing bars
- stale bars
- duplicate bars
- database read-only
- report directory failure

These are explicitly marked, not hidden.

## Invariants

- long-only preserved
- gross exposure <= 1.0
- position weight <= 0.15
- holdings <= 10
- no future data
- PIT preserved
- manual-only preserved
- broker_order_submitted=false
- LLM authority bounded
- Probability authority bounded

## Scorecard

- DATA: 100
- PIT: 100
- ALPHA: 0
- LLM: 100
- PROBABILITY: 100
- PORTFOLIO: 100
- RISK: 100
- OPERATIONS: 100
- RESILIENCE: 70

Total score does not hide critical failures. No critical failure occurred.

## Machine-readable summary

`reports/stress-exam/stress_exam_summary.json`

## Quality gates

- Full pytest: 967 passed
- quant_critical: 31 passed
- Ruff: All checks passed
- Strict mypy: 421 source files, no issues
- Secret scan: SECRET_SCAN_PASS

## Final classification

`STRESS_EXAM_PASS_WITH_WARNINGS`

Synthetic only; historical backtest and alpha certification remain separate
gates. ROUND20 scope is not defined in this prompt, so no further autonomous
round was started.