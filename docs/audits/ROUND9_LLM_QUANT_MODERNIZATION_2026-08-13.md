# ROUND 9 — LLM QUANT MODERNIZATION: SHADOW → ADVISORY INTELLIGENCE

Date: 2026-08-13
Branch: `codex/round9-llm-quant-modernization`
Baseline: ROUND 8 `CLASSICAL_CHAMPION_RETAINED` (commit `a160995`, pushed)

## Executive Summary

ROUND 9 completed the Personal Alpha Terminal modernization by building the
**LLM Intelligence Layer** as a pure bypass-proof side channel:

```text
Classical Quant Core  →  Formal Recommendation  →  LLM Intelligence Layer
```

The LLM never picks stocks, never sets a weight, and never bypasses a formal
quant gate.  The architecture is:

```text
Market/Security Data → PIT Layer → Universe → Features → Factors → Alpha →
Probability/Challenger → Portfolio Construction → Risk → Formal Recommendation
→ User Decision → Manual Schwab Execution → Actual Fill Ledger
```
with the side channel:
```text
SEC / News / Documents → LLM Intelligence → Shadow Evidence / Research / Explanation
```

## 1. Architecture

- **Classical Quant Core** remains the only source of formal recommendations.
- **LLM Intelligence Layer** is advisory-only: explanations, anomaly analysis,
  research copilot, shadow features.
- No LLM output can change a target weight, add a position, or create an action.

## 2. Structured Output Contracts

New `quant_engine/llm_advisory/contracts.py` (pydantic schemas):

- `AdvisoryEnvelope`: evidence, classification, confidence (0..1), timestamp,
  source, model, prompt_version.
- `DataAnomalyReport`: anomaly_kind (PROVIDER_FAILURE, STALE_DATA,
  UNIVERSE_COLLAPSE, CORPORATE_ACTION_ANOMALY), severity, affected symbols.
- `PortfolioExplanation`: natural-language explanation with
  `quant_impact ∈ {NONE, SHADOW}` — it has no target/quantity fields and can
  never change a target.
- `ResearchCopilotNote`: factor/regime/probability/attribution diagnostics.
- `ShadowFeatureSuggestion`: research-only feature proposal, `oos_validated`
  must be False until strict OOS validation.

Any numeric value is range-validated before use; empty classifications are
rejected.

## 3. Prompt Identity

`identity.py` — every invocation carries provider, model, model version, prompt
name/version, prompt hash (SHA-256 of the prompt text), schema version,
temperature and timestamp.  `identity_hash` makes behavior reproducible and
attributable.

## 4. Failure Isolation

`guard.py` — `LLMGuard.run` wraps any advisory callable.  Timeout, quota
exceeded, malformed JSON, hallucination risk and provider unavailability all
yield `LLMGuardStatus.DEGRADED` with `quant_impact=NONE` and
`fallback=CLASSICAL_CORE_CONTINUES`.  The Classical Quant Core is never blocked.

Real daily-run evidence (no LLM credential configured):

```text
LLM_INTELLIGENCE: OPTIONAL_UNAVAILABLE
  "advisory_status": "UNAVAILABLE",
  "advisory_quant_impact": "NONE",
  "fallback": "CLASSICAL_CHAMPION"
```

## 5. Advisory Capabilities

`service.py` — `AdvisoryIntelligenceService` assembles a deterministic
`AdvisorySnapshot` (status SHADOW/ADVISORY, model, PIT documents, anomalies,
explanations, copilot notes, shadow features, quant impact, fallback) from
validated contract outputs.  It never calls a provider itself; upstream LLM
failures are isolated by the guard.

## 6. LLM Evaluation

`evaluation.py` — `evaluate_llm` measures factual grounding, temporal
correctness, hallucination rate, consistency, structured-output validity, mean
latency, total cost and incremental quant value against fixed thresholds.  An
LLM cannot be adopted just because it "sounds smart".

## 7. LLM Shadow Research

`shadow_research.py` — `evaluate_llm_shadow_research` runs the strict OOS
comparison:

```text
Classical  vs  Classical + LLM Shadow Feature
```

The combined arm must improve net return, rank IC and Sharpe on the frozen OOS
sample (with a minimum OOS sample).  Missing evidence or insufficient sample →
`NOT_CERTIFIABLE`; no improvement → `NO_INCREMENTAL_VALUE` (LLM stays
explanation/research-assistant only).

## 8. Terminal Panel

The AI panel now shows:

```text
【AI 情报】
Status / Provider-model / Processed documents / PIT events /
SHADOW factor observations / Factor status / Production influence /
AI status (SHADOW|ADVISORY|UNAVAILABLE) / Quant impact (NO|SHADOW) /
Safe fallback (CLASSICAL_CHAMPION)
```

Users can see at a glance whether AI can affect trading (it cannot: impact is
NONE or SHADOW, fallback is always CLASSICAL_CHAMPION).

## 9. CLI

New `round9-research` command:
- `advisory-snapshot` — assemble a deterministic advisory snapshot
- `evaluate` — LLM quality evaluation against fixed thresholds
- `shadow-research` — Classical vs Classical+LLM shadow feature (strict OOS)

## 10. Acceptance Evidence

- `advisory-snapshot` → `Status: ADVISORY  Quant impact: NONE  Fallback: CLASSICAL_CHAMPION`
- `evaluate` → `Pass thresholds: True` (grounding 0.95, latency 150ms, cost $1)
- `shadow-research` → `Verdict: INCREMENTAL_VALUE` (with a genuine OOS improvement);
  a marginal/insufficient sample yields `NO_INCREMENTAL_VALUE` / `NOT_CERTIFIABLE`
- Real daily run: LLM disabled → `OPTIONAL_UNAVAILABLE` with
  `advisory_status=UNAVAILABLE`, `advisory_quant_impact=NONE`,
  `fallback=CLASSICAL_CHAMPION`; classical core continued and completed the run.

## 11. Tests Added

`tests/unit/quant_engine/llm_advisory/` (18 tests):
- structured-output contracts: required fields, numeric range validation,
  portfolio explanation cannot change targets, shadow feature OOS gate,
  copilot/anomaly kind validation
- prompt identity: traceable, deterministic, invalid temperature/empty rejected
- failure isolation: timeout, quota, malformed JSON degrade only LLM; success OK
- LLM evaluation: passes/fails on thresholds
- shadow research: min-sample, incremental value, no-value, missing-evidence
- advisory snapshot: status/quant-impact/fallback, invalid impact rejected
- terminal AI panel: renders SHADOW/ADVISORY status, quant impact, fallback

## 12. Quality Gates

| Gate | Result |
|---|---:|
| Full pytest | **869 passed** |
| Ruff | PASS |
| Strict mypy (405 source files) | PASS |
| Secret scan | PASS |
| Quant-critical regression | 31 passed |
| Performance smoke | 2 passed |

## 13. Final State

```text
Classical Quant Core:  CHAMPION / decides trades
LLM Intelligence:      ADVISORY / SHADOW evidence, research, explanation
Quant impact of LLM:   NONE or SHADOW only
Safe fallback:         CLASSICAL_CHAMPION
Auto execution:        DISABLED (manual Charles Schwab only)
```

## Final Verdict

**LLM QUANT MODERNIZATION: PASS (SHADOW → ADVISORY)**

The LLM Intelligence Layer is now a structured, audited, failure-isolated
advisory side channel.  It enhances research, explanation and anomaly analysis
but can never replace the Classical Quant Core or bypass a formal quant gate.
