# Production Signal Closure Report

Date: 2026-08-12

## 1. Latest Daily Run

Run: `daily-5b9f4d3812f14b329429fc2e79fc8796`

- Classification: `VALID_ANALYSIS_NON_ACTIONABLE`
- Analysis date: `2026-08-11`
- Trade date: `2026-08-12`
- Data cutoff: `2026-08-11T20:30:00+00:00`
- DATA: `PASS`
- PIT: `PASS`
- FEATURE: `PASS`
- FACTOR: `PASS`
- SIGNAL: `FAIL_BLOCKING`
- PROBABILITY: `PASS_DEGRADED`
- PORTFOLIO / RISK / DECISION / EXECUTION: `NOT_RUN`, blocked by SIGNAL
- actions: `0`
- final decisions: `0`
- canonical result hash:
  `97423b6bd112967b46e0e6a7279086cf4fd729961b672b2d0477da2035b98956`

The terminal explicitly prints `Actions 0` and the only primary blocker is:

```text
STRATEGY_NOT_PRODUCTION_APPROVED: no immutable approval backed by locked OOS,
PIT, survivorship-controlled and after-cost evidence
```

## 2. Root Cause

`SIGNAL FAIL_BLOCKING` is **not an engineering loading bug**.

Evidence:

- `model_approval_records`: `0`
- `model_registry`: `1`
- registered model status in `Production Approved`: `0`
- strategy candidate: `USAdaptiveAlphaCoreV1:1.0.0:427671e52a53`
- candidate state: `DIAGNOSTIC_ONLY`
- approval artifact: absent

The signal engine correctly loads 9 factor-eligible securities, computes
diagnostic alpha candidates, then refuses to promote them because no immutable
strategy approval exists.

## 3. Alpha / Approval Chain

Current chain:

```text
Factor -> Alpha Candidate -> Research Validation -> Approval Artifact ->
Production Registry -> Signal -> Probability -> Portfolio -> Risk ->
Recommendation
```

The chain stops at `Approval Artifact`. The registry and signal code can consume
an exact `PRODUCTION_APPROVED` artifact, as covered by automated tests, but no
real artifact has been earned.

No version mismatch, expired approval, shadow confusion, serialization failure,
or wrong environment was found.

## 4. Probability Influence

Latest probability overlay:

- state: `RESEARCH_ONLY`
- active in daily run: `false`
- fallback reason: `PROBABILITY_ARTIFACT_MISSING`
- expected return changed: `false`
- ranking changed: `false`
- target weight changed: `false`
- recommendation changed: `false`

The production path is wired so an exact approved artifact would influence
expected returns before portfolio construction, but that path is inactive.
Uncalibrated or fixture-only probability never changes a real recommendation.

## 5. Portfolio / Risk / Recommendation

Portfolio and risk are not run when SIGNAL is blocking. This is correct fail-closed
behavior. No BUY, ADD, REDUCE, SELL, or HOLD decision is fabricated from
diagnostic candidates.

## 6. Engineering Fix in This Closure

The historical research baseline now includes `required_end` in its identity.
This prevents a refresh from changing the required research end while reusing an
immutable baseline ID. This is an audit-chain stability fix and does not change
certification standards.

## 7. Conclusion

The correct interpretation is:

`SIGNAL FAIL_BLOCKING` is caused by missing real strategy evidence, not by a
pipeline bug. The system remains correctly non-actionable.
