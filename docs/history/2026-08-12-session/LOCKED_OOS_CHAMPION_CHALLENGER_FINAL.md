# Locked OOS Champion / Challenger Final

Date: 2026-08-12

Result: **NOT_RUN / NOT_CERTIFIABLE**

## 1. Frozen Research Definition

Champion: Classical Quant Core

Challenger: Classical Quant Core plus approved candidate LLM features

Current candidate:

- `llm_event_intensity`, `event-extraction-v2`, DeepSeek configured model
- status: `SHADOW`
- production influence: `false`

Benchmark-relative LLM probability research exists separately as research-only
input and is not production-active.

## 2. Split Policy

No temporal split has been opened.

Required chronology:

- 252 factor warmup
- 1008 TRAIN
- 504 VALIDATION
- 21 EMBARGO
- 252 locked OOS

Required total: 2037 sessions.

Required end: `2026-08-11`

Required minimum start: `2018-07-03`

Current real price coverage: `2024-08-07` to `2026-08-11`.

## 3. Dataset / Benchmark / Cost State

- Historical research dataset: `NOT_CERTIFIABLE`
- Historical text/event corpus: `NOT_CERTIFIABLE`
- SPY/QQQ same-PIT historical benchmark series: `NOT_AVAILABLE`
- Transaction-cost model exists as a deterministic model but no OOS PnL exists
- Gross and after-cost metrics: `NOT_RUN`

## 4. Ablation

Planned:

A. Classical only

B. Classical + `llm_event_intensity`

C. Classical + approved LLM probability feature

D. Classical + all approved LLM candidates

None of these runs is valid until both market and text datasets are certified and
the locked-OOS identity is frozen.

## 5. Promotion Gate

The gate now enforces:

- identical research dataset identity;
- identical universe identity;
- identical benchmark;
- identical cost model;
- identical portfolio/risk constraints;
- identical frozen locked-OOS definition;
- at least 252 observations per arm;
- complete metrics;
- after-cost excess return improvement;
- Rank IC improvement;
- no worse max drawdown;
- no worse Brier score or log loss.

The gate can return:

- `PRODUCTION_APPROVED`
- `REJECTED`
- `NOT_CERTIFIABLE`

It no longer collapses every blocker into `NOT_CERTIFIABLE`.

## 6. Real Metrics

No real Champion or Challenger OOS metrics are reported.

`NOT_RUN` is the truthful state. No simulated or fixture metrics were inserted.

## 7. Conclusion

Challenger remains `SHADOW`. Promotion is blocked by missing certified market
history, missing certified text history, and the absence of a frozen locked-OOS
experiment.
