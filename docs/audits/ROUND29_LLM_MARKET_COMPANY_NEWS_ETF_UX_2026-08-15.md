# ROUND29 — LLM Market Intelligence / Company Dossier / News Freshness / ETF UX

## Verdict

`ROUND29_FINAL_STATUS = PASS`

`FINAL_VERDICT = ROUND29_READY_FOR_QUANT_MODEL_INTEGRITY`

`READY_FOR_ROUND30 = YES`

## Runtime acceptance

Real daily-run completed under `--no-refresh` with run:

`daily-c3c0107d1d7641b49bbb81c32615fbbc`

The formal quant result remained authoritative: 10 stock BUY actions, no ETF
formal actions, manual-only execution, automatic execution DISABLED, broker API
DISABLED, probability production influence 0%.

Because the second live LLM call was blocked by the external-network safety
policy, the final AI grounding check uses the already-persisted LLM output from
that real run through a deterministic frozen replay:

`reports/validation-artifacts/round29_frozen_replay.json`

Replay result:

- status: `PASS`
- semantic validation: `AI_SEMANTIC_GROUNDING_OK`
- critical failure: `false`
- formal fields preserved: `true`

## LLM usage

From the real daily run:

- LLM calls: `4`
- prompt tokens: `21,518`
- completion tokens: `3,041`
- latency: `25,139 ms`

## Company dossiers

- dossiers built for formal action symbols: `10`
- market cap/size evidence sourced from current-only exposure metadata
- company name: `UNAVAILABLE` when no authorized external provider enrichment
  was available; no hallucinated company name is inserted
- all metadata remains `CURRENT_ONLY` / `NOT_HISTORICAL_PIT`

## News freshness

From the real run:

- raw rows: `60`
- normalized rows: `60`
- clusters: `58`
- terminal displayed: `9`
- freshness: `LAST_72H=1`, `LAST_30D=8`, `LAST_24H=0`, `LAST_7D=0`
- historical context separated from today's news
- `decision_cutoff_relation=PRE_DECISION` for displayed rows

## AI commentary

- action commentary count: `10`
- portfolio review present: `true`
- devil's advocate count: `10`
- LLM formal action/weight identity protection enforced

## ETF UX

- ETF formal actions: `0`
- ETF research observations: `55`
- terminal explicitly renders: `ETF 正式操作：0` and `无需执行任何ETF交易`
- research section title: `【ETF研究观察 · 不需要操作】`
- research rows show action needed `NO`, trading permission `NONE / RESEARCH_ONLY`

## Implemented ROUND29 changes

- `src/personal_alpha_terminal/ai_advisory/action_commentary.py`
- `src/personal_alpha_terminal/ai_advisory/brief_v2.py`
- `src/personal_alpha_terminal/ai_advisory/facts_v3.py`
- `src/personal_alpha_terminal/ai_advisory/renderer.py`
- `src/personal_alpha_terminal/intelligence/company_dossier.py`
- `src/personal_alpha_terminal/intelligence/market_news.py`
- `src/personal_alpha_terminal/application/round29_replay.py`
- `src/personal_alpha_terminal/application/daily_orchestrator.py`
- `src/personal_alpha_terminal/terminal/daily_renderer.py`
- tests under `tests/unit/ai_advisory/` and `tests/unit/application/`

## Test results

- full pytest: `1201 passed`
- quant-critical: `31 passed`
- quant regression: `317 passed`
- ROUND29 targeted tests: `39 passed`
- ruff: `PASS`
- mypy strict: `PASS (468 source files)`
- secret scan: `SECRET_SCAN_PASS`
- `git diff --check`: `PASS`

## Remaining known issues

- Live LLM re-run after the critical-section fix was not repeated because the
  sandbox policy blocks sending formal action data to the external provider
  without explicit approval. The frozen replay of the real LLM output passes.
- Company name and business narrative require explicit approval for an external
  provider enrichment endpoint; until then the terminal shows graceful
  `UNAVAILABLE` states.
- The original live AI brief was `PASS_DEGRADED_WHOLE_FALLBACK` because the LLM
  repeated formal numbers in a critical section. The fix keeps
  `executive_summary`, `formal_conclusions`, and `portfolio_risk_analysis`
  deterministic and passes the frozen replay.

## Final

`ROUND29_READY_FOR_QUANT_MODEL_INTEGRITY`

`READY_FOR_ROUND30 = YES`
