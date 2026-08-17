# ROUND53 Promotion Mathematics Correction

- Date: 2026-08-17
- Baseline SHA: `c6523d9bce1d71a2b7d50169f59624b07716a568`
- Scope: Agentic Shadow promotion evidence only.
- Production LLM lambda: `0`
- Formal production authority: Quant-only.

## P0 correction

The previous implementation derived `incremental_net_alpha` from the Hybrid
outcome itself. That could label a positive but Quant-underperforming Hybrid
portfolio as incremental alpha.

ROUND53 defines each paired observation as:

```text
incremental_net_alpha_t =
hybrid_net_return_t - quant_net_return_t
```

Promotion statistics now use only paired Quant/Hybrid counterfactual portfolio
snapshots. The pairing contract requires exact agreement on:

- decision timestamp;
- information cutoff;
- universe identity;
- evaluation horizon;
- execution assumptions;
- transaction cost model;
- slippage model;
- benchmark convention;
- data version.

Unpaired observations are excluded. If the remaining paired sample does not
meet policy, promotion is blocked with
`PAIRED_COUNTERFACTUAL_SAMPLE_INSUFFICIENT`.

## Metrics and gates

The evaluation records paired/sample N, mean and median incremental net alpha,
cluster-aware bootstrap confidence interval, incremental hit rate, turnover
delta, cost delta, drawdown delta, and regime/subperiod stability.

Promotion remains fail-closed when the mean incremental net alpha is not above
policy, the confidence lower bound is not strictly positive, calibration or
monotonicity is insufficient, turnover/drawdown limits fail, or regime
stability is not established.

## Adversarial regression

```text
Quant net return  = +1.9%
Hybrid net return = +0.9%
Incremental alpha = -1.0%
Expected status   = PROMOTION_BLOCKED_PERFORMANCE
```

The regression passes and returns
`INCREMENTAL_NET_ALPHA_BELOW_POLICY`.

## Validation

- Agentic intelligence unit tests: PASS, `23 passed`.
- Ruff on changed source/tests: PASS.
- Strict Mypy on changed source: PASS.
- Quant-critical governed regression: PASS, `31 passed`.

`ROUND53_VERDICT = PASS`

This round corrects evidence mathematics only. It does not activate Semantic
Alpha, change the Quant production decision path, or grant the LLM trading or
risk authority.
