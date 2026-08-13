# ROUND 12 - Operational Advisory Full Pipeline Closure

Date: 2026-08-13

## Verdict

`ROUND12_BLOCKED`

Implementation and automated isolated acceptance pass. The real LIVE_REFRESH run remains
non-actionable because the existing user-issued policy is validly signed but bound to a
different operational identity. The policy was not renewed, replaced, or bypassed.

The only operator action required before rerunning the live acceptance is:

```text
python main.py operational-policy create --decision ALLOW_PROVISIONAL
```

The command requires an interactive confirmation containing the current identity hash.
Daily operation never calls policy creation.

## Governance Closure

Research certification and operational authorization are now separate truths:

- Full research certification can authorize `PASS_PRODUCTION`.
- An explicit, unexpired, untampered, exact-identity `ALLOW_PROVISIONAL` policy can
  authorize `PASS_PROVISIONAL` and `PROVISIONAL_OPERATIONAL_ADVISORY`.
- All other cases remain `FAIL_BLOCKING`.

Provisional authorization does not change research evidence and cannot bypass DATA, PIT,
future-data, SIGNAL validity, portfolio, risk, cost, decision, or execution controls.

## Operational Identity V2

New policies bind schema `pat-operational-identity-v2`, including:

- strategy ID, version, definition hash, and parameter hash;
- factor definition and configuration hashes;
- operational universe definition;
- portfolio, risk, and transaction-cost hashes;
- Probability assessment artifact hash and production influence;
- stable LLM quant influence identity (`LLM_SHADOW_NONE`);
- canonical code/config fingerprint.

LLM connectivity, credentials, last-call status, and latency are intentionally excluded.
They cannot invalidate a policy because they have no quantitative authority.

Legacy v1 policies are parsed and verified against their original hash material before
being compared with v2. They fail closed with exact mismatch fields rather than being
reported as malformed.

## Current Policy Evidence

Stored policy:

- Policy ID: `operational-policy-129237232b6593e50473`
- Decision: `ALLOW_PROVISIONAL`
- Artifact hash: `129237232b6593e5047316c86239230e4aa144efb58c854b31446e05dcae02a1`
- Stored identity hash: `1a7c12b37b61238c39814450c329a18dbf0cbb9f376e1f79f5547bed768eb69c`
- Expires: `2026-08-19T00:00:00+00:00`
- Effective: `false`
- Reason: `OPERATIONAL_POLICY_IDENTITY_MISMATCH`
- Policy file SHA-256 after live acceptance:
  `35139388F2D1044AB7CE8A069E3D0DDEE9B27C0ABAA4EE9FB1558034E0F434E8`

Current v2 identity hash:
`d87d4c0cd69b8e319ae86f43c027e976d299aec31bd35c3b1d14000b60d0a32c`.

The status command reports stored/current values for every mismatch. Current differences
include the changed operational universe policy plus fields not bound by the v1 schema:
strategy/factor definitions, Probability artifact and influence, LLM influence identity,
and code/config fingerprint.

## Policy CLI And Storage

Canonical commands:

```text
python main.py operational-policy status
python main.py operational-policy create --decision ALLOW_PROVISIONAL
```

`status` emits sanitized hashes, expiry, effectiveness, exact mismatch fields, and a
runtime `CURRENT_OPERATIONAL_IDENTITY_REPORT`. `create` defaults to seven days and
requires an interactive exact-phrase confirmation. Noninteractive execution refuses to
create a policy.

New policy documents are immutable content-addressed artifacts. The active policy file is
only a reference containing policy ID, artifact hash, and artifact path. Artifact
overwrite, malformed reference, hash mismatch, ID mismatch, expiry, and identity mismatch
all fail closed. Existing legacy body-format policies remain readable.

## Signal And Pipeline Contract

Signals and run evidence now carry:

- authorization class;
- research certification state;
- operational policy ID/hash/identity hash;
- evidence level.

The existing real provisional pipeline remains unchanged: a matching isolated policy
executes portfolio construction, risk, and decision generation. Tests prove real
recommendations and trades are produced as provisional, never relabeled production
approved. Missing, expired, stale, or tampered policy paths remain blocked.

Run certificate classifications are now:

- `VALID_ANALYSIS_ACTIONABLE_CERTIFIED`
- `VALID_ANALYSIS_ACTIONABLE_PROVISIONAL`
- `VALID_ANALYSIS_NON_ACTIONABLE`

Certificates also persist Probability mode/influence, LLM mode, and explicit
`auto_execution=false`, `manual_execution_only=true`.

## Probability And LLM

Latest Probability assessment:

- Artifact ID: `round4-probability-1b0cc4ff552a7cca6a66`
- Artifact hash: `64376e645acbfd53fa0877121709bd0d560a311fd6c3e0d05d9d54ea55f5f284`
- Verdict: `NO_INCREMENTAL_ALPHA`
- Production influence: `0.0`

Daily mode remains
`PROBABILITY_FALLBACK_CLASSICAL:NO_INCREMENTAL_ALPHA`. Conditional probability is shown
as unavailable, not fabricated. Counterfactual target impact remains zero.

DeepSeek remained `AVAILABLE`, `SHADOW`, with production influence `NONE`. No LLM output
can modify alpha, probability, risk, target weight, or decisions.

## Real LIVE_REFRESH Acceptance

Run ID: `daily-725be882981a42ad984caad9d9fcd7c3`
Analysis date: 2026-08-12
Trade date: 2026-08-13
Data mode: `LIVE_REFRESH`
Runtime: 93.72 seconds

Universe funnel:

| Layer | Count |
|---|---:|
| Listed securities | 8,835 |
| Listed equities | 7,476 |
| Security type eligible | 4,957 |
| Latest-price covered | 4,953 |
| History sufficient | 4,534 |
| PIT eligible | 3,433 |
| Liquidity eligible | 2,128 |
| Factor eligible | 2,128 |
| Alpha positive | 1,165 |
| Candidate pool | 100 |
| Optimizer input | 100 |
| Final holdings | 0 |
| Quarantine | 1 |

Stage results:

| Stage | Result |
|---|---|
| DATA | PASS |
| PIT | PASS; future rows 0 |
| FEATURE | PASS |
| FACTOR | PASS; 2,128 observations |
| SIGNAL | FAIL_BLOCKING; policy identity mismatch |
| PROBABILITY | PASS_DEGRADED; Classical fallback |
| PORTFOLIO | NOT_RUN; blocked by SIGNAL |
| RISK | NOT_RUN; blocked by SIGNAL |
| DECISION | NOT_RUN; blocked by SIGNAL |
| PERSISTENCE | PASS |

Classification: `VALID_ANALYSIS_NON_ACTIONABLE`.

The live run proves broad current PIT data and alpha remain stable. It cannot prove the
real actionable provisional closure until the user explicitly signs the current identity.
No optimizer, risk, or decision result is claimed for this blocked live run.

## Quality Gates

- Final full pytest: `914 passed`.
- Quant-critical and operational-policy suite: `70 passed`.
- Future leakage/PIT suite: `12 passed`.
- Focused governance/pipeline/renderer suite: `66 passed`.
- CLI/certificate/governance suite: `61 passed`.
- Immutable-reference/CLI/provisional suite: `51 passed`.
- Ruff: PASS.
- strict mypy: PASS, 412 source files.
- Secret scan: `SECRET_SCAN_PASS`.
- Real LIVE_REFRESH: completed fail-closed.

## Remaining Acceptance Step

An operator must review the identity summary and explicitly run:

```text
python main.py operational-policy create --decision ALLOW_PROVISIONAL
```

After confirmation, rerun `python main.py daily`. Only a matching effective policy may
produce `PASS_PROVISIONAL` and exercise the live `PORTFOLIO -> RISK -> DECISION` path.
The final outcome may legitimately be BUY, SELL, HOLD, or NO_TRADE. Automatic broker
execution remains permanently disabled and Charles Schwab execution remains manual.
