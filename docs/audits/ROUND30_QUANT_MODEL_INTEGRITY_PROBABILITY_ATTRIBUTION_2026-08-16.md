# ROUND30 — Quant Model Integrity / Probability / Counterfactual / Attribution / Exposure / Regime

## Verdict

`ROUND30_FINAL_STATUS = PASS`

`FINAL_VERDICT = ROUND30_READY_FOR_PORTFOLIO_BREADTH_RESEARCH`

`READY_FOR_ROUND31 = YES`

ROUND30 does not claim that probability, market regime, current-only size
metadata, or LLM advisory text changed the formal target. It proves which
modules are ACTIVE in the formal decision chain and which remain at 0%
production influence.

## 1. Every module actually executed

The formal production path is:

`PIT DATA -> FEATURE -> FACTOR -> ALPHA -> SIGNAL -> PROBABILITY (0%) -> PORTFOLIO OPTIMIZATION -> RISK -> COST -> TURNOVER -> EXPOSURE -> DECISION -> EXECUTION PLAN`

Persisted evidence:

- Acceptance run: `daily-2420c68452d142298e6b42482341391f`
- Decision manifest: `def9b6be383088f6dc6d88308cc80623c5733f710aa98fbbe95cf589d246d16b`
- Optimizer input: `1171`
- Final formal actions: `10`
- Fixed holdings cap: `null`
- Pre-optimizer Top-N truncation: `null`
- Expected vol: `7.60%`
- Gross: `27.23%`
- Cash: `72.77%`

`reports/validation-artifacts/model_influence_registry.json` records 12 modules:

| Module | Status | Production authority | Production weight |
|---|---|---:|---:|
| Factor models | ACTIVE | Formal decision input | 1.0 |
| Alpha model | ACTIVE | Formal decision input | 1.0 |
| Probability model | RESEARCH_ONLY | NONE | 0.0 |
| Covariance model | ACTIVE | Optimizer input | 1.0 |
| Risk model | ACTIVE | Formal risk gate | 1.0 |
| Liquidity model | ACTIVE | Optimizer bound and trade cost | 1.0 |
| Transaction cost model | ACTIVE | Optimizer objective and execution cost | 1.0 |
| Portfolio optimizer | ACTIVE | Final target weight | 1.0 |
| Market regime | OBSERVATION_ONLY | NONE | 0.0 |
| Size exposure | DEGRADED | Next-trade metadata only | 0.0 |
| Sector exposure | ACTIVE_OPTIMIZER_CONSTRAINT | Optimizer sector cap via risk metadata | 1.0 |
| LLM | ADVISORY_ONLY | NONE | 0.0 |

## 2. Probability ledger integrity

`reports/validation-artifacts/probability_promotion_ladder.json` and the
existing forward ledger audit confirm:

- raw prediction rows: `90`
- canonical predictions: `26`
- duplicate/occurrence rows: `64`
- matured outcomes: `0`
- effective N: `0`
- decision dates with matured outcomes: `0`
- production influence: `0.0`

The ledger remains append-only. Replay/debug/test/backfill/report-only rows do
not create predictions; same-semantic reruns are occurrences, not new OOS
observations. Outcome maturity uses the frozen 21-session benchmark-relative
definition and cannot see future bars.

## 3. Probability promotion ladder

The explicit ladder is conservative and never auto-promotes:

- `RESEARCH_ONLY`: 0%, no mature evidence or a gate fails
- `OBSERVATION`: 0%, ledger audited but sample insufficient
- `LIMITED_PRODUCTION`: 5%, requires N >= 60, decision dates >= 5, OOS lift >= 1.10, CI lower >= 1.00, ECE <= 0.15, Brier <= 0.25, after-cost alpha > 0, stability, and human approval
- `PRODUCTION`: 10%, requires N >= 120, decision dates >= 10, OOS lift >= 1.20, CI lower >= 1.05, ECE <= 0.10, Brier <= 0.22, after-cost alpha > 0, stability, and human approval

Current stage: `RESEARCH_ONLY`. This is not a failure. Probability may not
become production-influential until real matured outcomes exist and all gates
pass.

## 4. Counterfactual / ablation

`reports/validation-artifacts/quant_counterfactual_audit.json` uses a
deterministic fixture with the same production construction engine and is
explicitly labelled `FIXTURE_OOS_STYLE`. The ROUND27 acceptance certificate
does not persist the full 1,171-asset covariance, returns, ADV, and alpha
arrays, so it is not represented as a production 1,171-asset ablation.

Fixture result summary:

| Run | Target count | Gross | Turnover | Expected vol | Est cost | Expected alpha |
|---|---:|---:|---:|---:|---:|---:|
| A full | 3 | 30.00% | 30.00% | 3.34% | 207.43 | 4.583% |
| B no probability | 3 | 30.00% | 30.00% | 3.34% | 207.43 | 4.583% |
| C no transaction cost | 3 | 30.00% | 30.00% | 3.38% | 0.00 | 4.608% |
| D no liquidity | 3 | 30.00% | 30.00% | 3.38% | 165.00 | 4.608% |
| E no covariance | 3 | 30.00% | 30.00% | 2.44% | 207.43 | 4.583% |
| F no turnover | 3 | 30.00% | 30.00% | 3.34% | 207.43 | 4.583% |
| G no exposure constraints | 4 | 36.00% | 36.00% | 3.92% | 248.91 | 5.339% |
| H only factor/alpha | 1 | 98.50% | 98.50% | 13.49% | 0.00 | 16.123% |

Probability ON/OFF is identical because production influence is 0%. Cost,
liquidity, covariance, turnover, exposure, and only-alpha runs changed target
weights or portfolio metrics, proving these code paths are not display-only in
the fixture. Per-asset records use paired marginal/counterfactual impacts, not
fabricated additive decomposition.

## 5. Per-asset contribution

The audit writes `per_asset_marginal_contribution` for each module variant.
Values are paired `full_weight - disabled_weight` impacts. No additive
decomposition is asserted because optimizer weights are nonlinear.

## 6. Size / sector exposure

- Formal portfolio current size coverage: `100%`
- Formal portfolio current sector coverage: `100%`
- Candidate PIT size coverage: remains unavailable/unknown
- Candidate current-only coverage: not expanded because provider enrichment was
  not approved or unavailable in this round
- Boundary: `CURRENT_ONLY_RISK_METADATA / NOT_HISTORICAL_PIT / NOT_FOR_BACKTEST`

Today's market cap is never backfilled into historical PIT. Size exposure
remains `DEGRADED` in the formal participation panel; sector exposure remains
an active optimizer constraint via risk metadata.

## 7. Market regime

`market-regime-v1` is deterministic and now reports `OBSERVATION_ONLY`. It never
controls gross, risk budget, or vol target in this phase. Its inputs are PIT
trend, breadth, dispersion, realized volatility, correlation, and drawdown
where available. The no-lookahead test confirms future dated observations are
ignored.

## 8. Terminal participation panel

The daily renderer now shows `【本次正式参与决策】` immediately after the
overview:

- Alpha: ACTIVE
- Probability: RESEARCH_ONLY / 0%
- Covariance: ACTIVE
- Risk: ACTIVE
- Liquidity: ACTIVE
- Transaction cost: ACTIVE
- Turnover: ACTIVE
- Size constraint: DEGRADED
- Sector constraint: ACTIVE
- Market regime: OBSERVATION_ONLY
- LLM: ADVISORY_ONLY / NONE

## 9. Test results

- full pytest: `1210 passed`
- quant-critical: `31 passed`
- quant regression: `317 passed`
- PIT / leakage / semantic / ROUND30 combined: `56 passed`
- ROUND30 model integrity final targeted: `7 passed`
- CURRENT_STATUS consistency: `3 passed`
- ruff: `PASS`
- mypy strict: `PASS (470 source files)`
- secret scan: `SECRET_SCAN_PASS`
- `git diff --check`: `PASS` (LF/CRLF warnings only)

## 10. Remaining known limitations

- The exact production 1,171-asset counterfactual cannot be recreated from the
  acceptance certificate because full optimizer inputs were not persisted.
  The counterfactual audit is transparently labelled fixture/OOS-style.
- Probability has 0 matured outcomes and therefore 0% influence.
- Candidate current-only size/sector coverage remains unknown where provider
  enrichment was not available.
- Live LLM calls remain blocked by external-network policy; ROUND29 frozen
  replay continues to govern AI grounding validation.

These limitations are recorded as evidence boundaries, not hidden P0 failures.

## Artifacts

- `reports/validation-artifacts/model_influence_registry.json`
- `reports/validation-artifacts/probability_promotion_ladder.json`
- `reports/validation-artifacts/quant_counterfactual_audit.json`
- `reports/validation-artifacts/decision_participation.json`
- `reports/validation-artifacts/round30_validation_summary.json`
- `docs/CURRENT_STATUS.json`
- `docs/CURRENT_STATUS.md`

## Final

`ROUND30_FINAL_STATUS = PASS`

`FINAL_VERDICT = ROUND30_READY_FOR_PORTFOLIO_BREADTH_RESEARCH`

`READY_FOR_ROUND31 = YES`
