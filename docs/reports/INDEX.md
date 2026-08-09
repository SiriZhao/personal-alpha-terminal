# Reports index

The canonical machine-readable status is [CURRENT_STATUS.json](../CURRENT_STATUS.json),
rendered as [CURRENT_STATUS.md](../CURRENT_STATUS.md). Historical reports below this
directory are retained as audit evidence, but are **SUPERSEDED** for current readiness.

## Current validation records

| Document | Status | Meaning |
|---|---|---|
| [Data Certification Final Report](../DATA_CERTIFICATION_FINAL_REPORT.md) | Current evidence | Latest real provider/certification result; not an Alpha approval. |
| [Phase 1 Final Closure Part 1](../PHASE1_FINAL_CLOSURE_PART1.md) | Current engineering checkpoint | Configuration, approval, probability, and hash-chain contracts. |
| [Phase 1 Final Closure Part 2](../PHASE1_FINAL_CLOSURE_PART2.md) | Current after generated | Risk, execution, vertical verification, QA, and release evidence. |

Everything under `audit/`, `data/`, `release/`, `security/`, `strategy/`, and
`validation/` is historical reference unless a current document above explicitly cites it.
Words such as PASS, production, release, or approved inside those files describe their own
checkpoint and do not override the current Data/PIT/Locked-OOS/Live-Capital gates.
