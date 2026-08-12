# Actionable Daily Run Closure

Date: 2026-08-12

## 1. Real E2E Run

Run ID:

`daily-e8ee28b3ba9444f4bb81658b61dd6b16`

Certificate:

`reports/daily-runs/daily-e8ee28b3ba9444f4bb81658b61dd6b16/run_certificate.json`

Machine-readable output:

`artifacts/latest/provisional_daily_run.json`

## 2. Run Identity

- analysis date: `2026-08-11`
- trade date: `2026-08-12`
- data cutoff: `2026-08-11T20:30:00+00:00`
- data snapshot: `US-20260812T041448Z-fca2e8ce398f`
- data hash: `fca2e8ce398f67fe95ff9562b2ff1de01ede6ce4fdecb1ee57a8ac1fe29ab8ba`
- canonical input hash: `7e9c5b8496d179ad83abc8bb2fa2e0b76ff366238c2e1eb840cf77c48a5d5283`
- canonical result hash: `b9df35d4bf1eec032603265369d5f05a6faca9261fd5d0a62d463c0a0738c4c4`

## 3. Pipeline State

- DATA: `PASS`
- PIT: `PASS`
- FEATURE: `PASS`
- FACTOR: `PASS`
- SIGNAL: `PASS` (`PROVISIONAL_OPERATIONAL_APPROVED`)
- PROBABILITY: `PASS_DEGRADED` / `RESEARCH_ONLY`
- PORTFOLIO: `PASS`
- RISK: `PASS`
- DECISION: `PASS`
- EXECUTION: `PASS`
- LLM: `OPTIONAL_UNAVAILABLE`, classical Quant continued

## 4. Research State

```text
RESEARCH_CERTIFICATION = NOT_CERTIFIABLE
OPERATIONAL_READINESS = PROVISIONAL_ACTIONABLE
ROUND_3_MARKET_DATA_DEPENDENCY = BLOCKED
```

## 5. Recommendations

Actions count: `3`

| Symbol | Action | Current | Target | Delta | Qty | Estimated Cost |
|---|---:|---:|---:|---:|---:|---:|
| AAPL | BUY | 0.0% | 6.0% | 6.0% | 19 | 3.30 |
| GOOGL | BUY | 0.0% | 12.0% | 12.0% | 34 | 6.61 |
| JNJ | BUY | 0.0% | 12.0% | 12.0% | 46 | 6.63 |

Portfolio target: 30% invested, 70% cash, expected volatility 5.50%, turnover
30%, HHI 0.0324, stress PASS.

Risk reduction:

`size_neutralization:degraded`

This is explicitly recorded because current `market_cap` is unavailable.

## 6. Determinism

Repeated runs with the same:

- data snapshot
- cutoff
- config
- holdings

produced the same canonical result hash:

`b9df35d4bf1eec032603265369d5f05a6faca9261fd5d0a62d463c0a0738c4c4`

## 7. LLM Influence

`LLM_INFLUENCE = NONE`

DeepSeek did not change the recommendation.

## 8. Interpretation

This is a real current-day operational recommendation from deterministic
quant factors. It is not long-horizon Alpha certification. Manual broker
confirmation is required. No automatic execution is enabled.
