# ROUND70 — LLM Decision Promotion (2026-08-18)

## Scope and verdict

- Starting SHA: `aa173b44001e663f9bc1cb0ff40701efbf3af15a`
- Final SHA: recorded by the dedicated ROUND70 commit (`git show -s --format=%H HEAD`)
- Policy verdict: **PASS_WITH_WARNINGS** for the additive architecture; **LLM formal influence remains 0**.
- Promotion decision: **RETAIN QUANT CHAMPION / LLM SHADOW (L1)**.
- No model, optimizer, risk, execution, or broker policy was promoted.

ROUND70 adds a typed LLM decision contract, evidence provenance, disagreement
classification, bounded fusion helpers, and a compact Chinese operator view.
The existing AgenticDecisionEngine remains the integration point and continues
to fail soft to the deterministic quant path.

## Old role and new role

Before ROUND70, the AgenticDecisionEngine already produced structured market,
stock, and portfolio commentary plus shadow alpha attribution. Production
formal influence was gated to zero unless a promotion certificate passed.

After ROUND70, the LLM can express a richer, machine-readable decision packet:

- market regime, risk budget, exposure, macro/event risk, breadth/trend interpretation, uncertainty;
- company summary, business quality, developments, catalysts, risks, conviction, ranking and position adjustments, urgency, warning, reasoning;
- portfolio view, exposure/risk-budget adjustment, concentration warning, major risks, and rebalance urgency.

Each material claim can carry source, observed/available timestamps, freshness,
confidence, evidence IDs, and an explicit evidence state:
`VERIFIED`, `STALE`, `UNKNOWN_UNVERIFIED`, or `CONFLICTING`.

## Exact influence surfaces

The additive fusion layer supports bounded influence on:

- candidate ranking and conviction adjustments;
- event-risk penalties and catalyst interpretation;
- target exposure/risk-budget preferences;
- rebalance urgency and holding-retention review;
- disagreement records between the Quant view and LLM view.

`bounded_fusion()` clamps every numeric adjustment, rejects non-finite values,
and returns the unchanged Quant scores whenever hard constraints fail. The
existing optimizer and Risk Engine remain the formal target-weight authority.

## Influence ladder and current level

The new explicit ladder is:

| Level | Meaning |
| --- | --- |
| L0_COMMENTARY | explanation only |
| L1_SHADOW_SCORING | measurable shadow score, zero production effect |
| L2_RANKING | ranking counterfactual only |
| L3_BOUNDED_FORMAL | bounded formal overlay after promotion evidence |
| L4_ADAPTIVE_EVIDENCE | contextual formal influence after stronger evidence |

Current effective state is **L1_SHADOW_SCORING**, with `formal_influence = 0`.
The resolver cannot reach L3/L4 unless promotion evidence, verified evidence,
and an explicit production-enabled policy all pass. ROUND67 data/PIT,
survivorship, and locked-OOS limitations therefore continue to block promotion.

## Hard constraints and fail-safe behavior

The LLM cannot bypass:

- long-only policy, tradability, liquidity, data-quality/PIT gates;
- hard risk and concentration limits;
- optimizer final authority;
- manual confirmation;
- `auto_execution = DISABLED` and broker-order prohibition.

Malformed JSON/schema, provider timeout/unavailability, future evidence,
unknown candidate identity, or unsupported event references produce a
`FAIL_SOFT_QUANT_ONLY` result. The attached `DecisionAudit` records degraded
AI status, failure reason, deterministic fallback, provenance, and the fact
that no stale LLM result was reused.

## Disagreement and evidence examples

The audit classifies each candidate as one of:

`STRONG_AGREEMENT`, `WEAK_AGREEMENT`, `LLM_MORE_BULLISH`,
`LLM_MORE_BEARISH`, `EVENT_CONFLICT`, `FUNDAMENTAL_CONFLICT`, or
`DATA_UNCERTAIN`.

When evidence is stale, missing, future-dated, or conflicting, the fusion
result is `QUANT_ONLY` or a bounded review flag; it is never an unrestricted
LLM veto or weight change. Extreme bullish/bearish suggestions are numerically
clamped, and a hard-risk failure returns the original Quant scores unchanged.

## Terminal integration

`terminal.hybrid_intelligence` now renders a compact `【LLM 决策审计】` section
when a persisted closure contains `llm_decision_audit`, showing influence level,
formal influence, degraded status, portfolio/risk reason, disagreement state,
and per-symbol Quant-vs-LLM fusion results. Detailed provenance remains in the
artifact rather than the normal daily frame.

## Evidence required for next promotion

Promotion above L1 requires, at minimum:

1. reproducible PIT and survivorship-safe historical evidence, including symbol
   changes and delistings;
2. an immutable locked-OOS protocol with enough independent observations,
   model/config/schema hashes, and no post-hoc tuning;
3. event/company provenance with decision-time availability and freshness;
4. deterministic replay across provider failures, stale/conflicting evidence,
   and extreme suggestions;
5. statistically meaningful incremental benefit versus the Production Quant
   Champion with acceptable drawdown, turnover, concentration, and costs;
6. hard-risk override and manual-confirmation evidence in the production path.

Until those gates pass, LLM output is research/shadow evidence only.

## QA

- Focused agentic + fusion + terminal tests: **15 passed**.
- Round66 production-intelligence tests: **5 passed**.
- Ruff (changed modules/tests, cache redirected to writable temp): **PASS**.
- Strict mypy (changed modules): **PASS**; full-package invocation completed without diagnostics.
- Secret scan: **SECRET_SCAN_PASS**.
- Quant-critical suite: **BLOCKED during collection** because the managed
  runtime lacks `exchange_calendars` (23 collection errors; 1214 tests
  deselected). No dependency was fabricated or silently skipped.
- Full pytest: **BLOCKED during collection by the same missing dependency**;
  existing `.pytest_cache` ACL/WinError warnings were also observed.

Inherited dirty files from the ROUND69 checkpoint were preserved and are not
part of the ROUND70 commit.
