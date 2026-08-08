# Intelligence & Research Engine Phase B Report

**Project version:** 1.1.0  
**Phase:** Intelligence / Research P1  
**Status:** Implemented and fixture-tested; real-data production promotion remains blocked  
**Repository state:** The project is inside an uncommitted parent worktree with no Git `HEAD`; no commit hash can be recorded.

## 1. P1 completed modules

| Capability | Engineering status | Validation status | Production influence |
|---|---|---|---|
| Hypothesis registry and research budget | Implemented | Deterministic fixtures | None by default |
| Multiple-testing and promotion gate | Implemented | FDR/noise/PIT tests | Manual gate required |
| Market relationship graph | Implemented | PIT/statistical fixtures | Research context only |
| Narrative detection and decay | Implemented | PIT/decay/diversity fixtures | Zero default weight |
| Narrative-to-asset exposure | Implemented | Frozen event fixtures | Research only |
| Cross-asset context | Implemented | Supplied-series fixtures | Context only |
| Signal-fusion guardrails | Implemented | Authorization tests | P1 weights default to zero |
| Opportunity Scanner integration | Implemented | Full service integration | Cannot create target weights |
| Decision lineage | Implemented | SQLite replay/integrity tests | Audit only |
| Backtest comparison matrix | Implemented | OOS/cost fixture tests | Research comparison only |

No Phase B feature was validated on certified real market/news data. Therefore none of the new Narrative, Relationship, or Hypothesis features is a production Alpha feature.

## 2. Hypothesis Engine

The engine stores versioned formal definitions with preregistered conditions, target, benchmark, horizon, chronological discovery/validation/test periods, model version, PIT cutoff, and backtest-safety status. It validates only observations whose outcome is visible at the evaluation cutoff.

Controls implemented:

- per-run hypothesis, parameter, threshold, and horizon budgets;
- minimum total and OOS samples;
- after-cost minimum effect;
- FDR correction;
- OOS effect/stability, regime stability, drawdown, and turnover gates;
- duplicate-session and feature-availability leakage rejection;
- `PROPOSED → FORMALIZED → TESTING → VALIDATED/REJECTED/RETIRED` lifecycle;
- no automatic production promotion.

A validated result becomes only `VALIDATED_RESEARCH_FEATURE`. Production eligibility additionally requires certified real PIT data and explicit manual approval.

## 3. Relationship Graph

Nodes support stocks, ETFs, sectors, indices, macro series, and narratives. Edges support correlation, rolling correlation, lead-lag, conditional association, event co-exposure, narrative co-exposure, and sector relations.

Each materialized statistical edge records effective sample size, confidence interval, raw and FDR-adjusted p-values, regime, rolling strength, stability, decay, OOS survival, model/data versions, cutoff, blockers, and a mandatory causal disclaimer.

Edges do not create trades. Without statistical significance, economic usefulness after costs, and OOS survival they remain `RESEARCH_INSIGHT`.

## 4. Narrative Engine

Narratives are built only from already materialized, schema-validated events visible at the requested PIT cutoff. The engine calculates bounded strength, momentum, acceleration, source diversity, entity breadth, novelty, persistence, sentiment change, and exponential decay.

Safeguards:

- one event contribution is capped;
- an emerging narrative requires multiple independent sources;
- future event/evidence updates are invisible;
- asset mappings retain evidence, confidence, cutoff, decay, and safety status;
- narrative momentum remains `RESEARCH_ONLY`.

Known-taxonomy aliases are configurable; unknown themes can emerge from diverse evidence rather than a fixed keyword-only list.

## 5. Quant Core and Scanner integration

The application service now exposes one integrated boundary:

```text
Quant Core → Risk Model → Portfolio Construction → Trade Proposals
                                      +
                 PIT Intelligence Research Context
                                      ↓
                         Opportunity Scanner
```

The integrated pipeline runs Quant Core first. A critical Data Gate, PIT, Risk, Portfolio, or Trade Generator failure returns `BLOCKED` and no candidate. Optional Intelligence failure degrades explicitly to `QUANT_ONLY` while preserving deterministic Quant Core output.

The Scanner can only display a target weight already produced by Portfolio Construction. It cannot invent a weight or change the Portfolio/Risk result. P1 research context is traceable but has zero default score influence.

## 6. Promotion Gate and signal-fusion guardrails

Central settings now control research budgets, narrative decay/breadth/persistence, relationship windows/samples/FDR/effect/OOS survival, hypothesis sample/effect/stability/drawdown/turnover, and maximum Intelligence contributions.

Engineering defaults are not represented as optimal parameters. Defaults are:

- AI feature contribution: `0`;
- Narrative, Relationship, and Hypothesis scanner weights: `0`;
- individual P1 contribution caps: `5%` if a future real-data OOS approval enables a weight.

Only `PRODUCTION_APPROVED`, PIT-safe, real-data-validated, non-expired features can affect fusion. Research-only features remain visible in explanations but contribute zero.

## 7. PIT, leakage, replay, and audit trail

All new time-bearing schemas require timezone-aware timestamps. Narrative and relationship inputs reject future observations. Hypothesis observations distinguish signal time, feature availability, and outcome availability. The integrated boundary rejects an Intelligence cutoff later than the daily decision time.

Frozen events, narratives, relationships, hypotheses, research results, and decision lineage are persisted with schema/model/data/prompt versions where applicable. Immutable hashes prevent an existing identity from being silently overwritten. Replaying the same frozen input produced identical snapshots, research features, rankings, targets, and risk flags in tests.

Decision lineage records:

```text
decision → portfolio result → quant signal → probability → event
         → narrative → relationship → hypothesis → raw evidence
```

Unavailable layers are recorded explicitly.

## 8. OOS, walk-forward, noise test, and backtest matrix

Hypothesis validation uses non-overlapping chronological discovery, validation, and test periods; random shuffling is not used. The deterministic synthetic-noise test applies FDR and economic/OOS gates and did not promote excessive random patterns.

The comparison matrix supports:

- `QUANT_ONLY`;
- `QUANT_EVENT`;
- `QUANT_EVENT_PROBABILITY`;
- `FULL_VALIDATED_INTELLIGENCE`.

It reports cost-adjusted CAGR/alpha, Sharpe, Sortino, Calmar, maximum drawdown, volatility, turnover, win rate, profit factor, exposure, gross return, net return, and cost drag. It rejects future, unsorted, duplicated, insufficient, or non-finite series. These tests used frozen fixtures, not real Alpha evidence.

## 9. Storage and migration

Alembic head: `e7f1b3c9a620`.

Added tables:

- `intelligence_hypotheses`;
- `intelligence_relationships`;
- `intelligence_narratives`;
- `intelligence_narrative_exposures`;
- `intelligence_decision_lineage`.

The migration upgrades and downgrades without database recreation. All foreign keys have a leading index; one missing decision-lineage index was found by the full regression and fixed.

## 10. Test and static-analysis evidence

| Check | Result |
|---|---|
| Phase A + Phase B Intelligence targets | **48 passed** |
| New Phase B module coverage | **92% total** |
| Research/PIT critical module coverage | **90–95%** |
| Database schema and Alembic tests | **11 passed** |
| Top-level unit group A | **143 passed** |
| Top-level unit prefix before VectorBT | **50 passed** |
| Top-level unit tail after VectorBT | **80 passed** |
| PostgreSQL backup/ACL tests outside sandbox | **7 passed** |
| Quant Core tests | **35 passed** |
| Dashboard + Integration + Performance | **78 passed** |
| Ruff, Phase B changed scope | **PASS** |
| Mypy strict, Phase B source scope | **PASS (25 source files)** |
| `pip check` | **PASS** |

The complete 448-test single command did not finish within ten minutes. After correcting the Windows temporary-directory ACL setup, it identified one real Phase B regression (the missing foreign-key index), which was fixed and retested. PostgreSQL backup failures under the sandbox were reproduced as ACL identity loss and passed 7/7 outside the sandbox.

The existing `tests/unit/test_quant_backends.py` did not complete: its first VectorBT test remained in the optional backend import/execution path beyond three minutes on Python 3.14. This is **BLOCKED BY ENVIRONMENT / OPTIONAL BACKEND**, not marked passed. Full-repository Ruff is also not green because pre-existing `terminal/` files contain 53 formatting/unused-import findings outside this phase; changed Phase B scope is clean.

## 11. Research-only versus production features

### Research-only

- every Phase B Hypothesis result in current fixtures;
- Narrative strength/momentum/asset exposure;
- Relationship and lead-lag context;
- Cross-asset context;
- Full-Intelligence backtest variants;
- AI Narrative/Relationship/Hypothesis agent outputs.

### Production

No new Phase B feature entered production. Existing Quant Core `PRODUCTION_APPROVED` Alpha signals, Portfolio Construction, and Risk Engine remain the only authorities for target weights and proposals.

## 12. Known limitations

- no certified point-in-time news/narrative archive was supplied;
- no real OOS Narrative or Relationship economic validation was performed;
- no professional supplier/customer graph or historical entity-map archive is available;
- cross-asset availability depends on the later data-stabilization phase;
- free data cannot prove full historical universe, delisting, and corporate-action completeness;
- relationship tests establish association, not causation;
- Hypothesis manual approval is an engineering gate, not evidence of investment merit;
- the Git parent has no `HEAD`, so run manifests cannot yet record a valid commit hash;
- no automatic trading or broker integration was added.

## 13. Data Stabilization handoff

The next data phase should provide, without changing these research contracts:

1. versioned PIT news/earnings/macro archives with source-update history;
2. stable provider lineage and immutable data snapshots;
3. certified US trading calendar and session mapping;
4. entity/security identifier history for ticker changes, mergers, and delistings;
5. point-in-time fundamentals and corporate actions;
6. stable cross-asset series for SPY, QQQ, IWM, sector ETFs, VIX, Treasury, USD, gold, oil, and BTC;
7. real walk-forward/OOS materialization before any P1 feature weight is enabled.

Until those requirements pass, the correct state is **Research Preview / Quant-only production authority / Intelligence research-only**.
