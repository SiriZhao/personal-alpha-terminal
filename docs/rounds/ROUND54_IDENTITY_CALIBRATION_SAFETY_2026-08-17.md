# ROUND54 Identity and Calibration Safety

- Date: 2026-08-17
- Baseline SHA: `69beece956c2c87e603d3ac7be297faa624f268f`
- Production LLM lambda: `0`
- Formal production authority: Quant-only.

## Canonical identity

ROUND54 introduces `SecurityIdentity` with:

- `permanent_security_id`;
- `company_id`;
- display `symbol`;
- `symbol_as_of_time`.

Company events require canonical identity. The structured company thesis,
company profile, information pack, forward prediction, and forward outcome
carry the same identity. Formal parsing, Quant x LLM debate, outcome attachment,
calibration, promotion, and counterfactual pairing fail closed on identity
mismatch.

Ticker is not used to guess or remap an unknown company. Hallucinated symbols,
wrong permanent IDs, wrong-company events, wrong-company outcomes, and
cross-security event revisions are hard rejected.

Event deduplication and event-analysis cache identity now include canonical
security identity. Identical text for different companies cannot be merged or
reuse another company's cached analysis.

## Calibration invalidation

`SemanticAlphaCalibrator.fit()` invalidates all previous fitted state before
evaluating new evidence. The following states retain no slope, intercept,
bucket, isotonic, or fit-cutoff state:

- `EVIDENCE_INSUFFICIENT`;
- `INVALID_FIT`;
- `FAILED_CALIBRATION`;
- `REJECTED`;
- any other non-active calibration state restored from disk.

`predict()` returns zero unless:

- calibration status is `CALIBRATING`;
- the score is finite;
- a valid fit-availability timestamp exists;
- the new prediction time is strictly after every training outcome used.

This prevents stale coefficients and overlapping train/prediction-time leakage
from producing non-zero Semantic Alpha.

## Validation

- Agentic intelligence unit tests: PASS, `28 passed`.
- Wrong-company event hard rejection: PASS.
- Hallucinated/wrong thesis identity rejection: PASS.
- Cross-security outcome rejection: PASS.
- Cross-security event dedup/cache isolation: PASS.
- Stale calibration invalidation: PASS.
- Temporal calibration-use guard: PASS.
- Ruff on changed source/tests: PASS.
- Strict Mypy on changed source: PASS.
- Quant-critical governed regression: PASS, `31 passed`.
- Existing hybrid terminal compatibility: PASS, `2 passed`.

`ROUND54_VERDICT = PASS`

No production Semantic Alpha authority was enabled.
