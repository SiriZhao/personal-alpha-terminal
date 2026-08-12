# AI-Native Champion / Challenger Report

Champion: existing classical deterministic quant chain.

Challenger: classical chain plus `llm_event_intensity` and the separately calibrated
benchmark-relative probability input.

Decision: `NOT_CERTIFIABLE`; Challenger remains `SHADOW`; no replacement occurred.

There are no truthful BASE-vs-LLM locked-OOS metrics to report. Blocking evidence is:

1. `RESEARCH_MARKET_DATA_NOT_CERTIFIED`
2. `HISTORICAL_TEXT_PIT_NOT_CERTIFIED`
3. `LOCKED_OOS_NOT_OPENED`
4. `CHAMPION_CHALLENGER_OOS_EVIDENCE_UNAVAILABLE`

The evaluator now requires an exact `ChampionChallengerIdentity` for both arms:
same research dataset, universe, benchmark, cost model, portfolio/risk
constraints, and locked-OOS definition. It also requires at least 252
locked-OOS observations per arm, complete metrics, improvement in after-cost
excess return and Rank IC, no worse drawdown, and no worse Brier/log-loss
calibration. The gate can return `PRODUCTION_APPROVED`, `REJECTED`, or
`NOT_CERTIFIABLE`; it cannot promote on availability alone.
