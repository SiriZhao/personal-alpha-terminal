# ROUND44 Structured LLM Thesis Engine

- Date: 2026-08-17
- Engineering status: PASS
- Economic influence: 0%

Implemented `LLMCompanyThesis` with stance, confidence, event dimensions,
horizon, bull/bear cases, catalysts, invalidation, risk flags and evidence
event ids. Unsupported ids fail validation; claims without source are marked
`UNSUPPORTED_CLAIM` and confidence is capped.

The schema has no target-weight field.
