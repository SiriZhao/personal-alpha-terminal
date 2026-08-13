# ROUND 13.1 — Intelligence Recovery & Real Acceptance Closure

Date: 2026-08-13

Verdict: `ROUND13_1_BLOCKED_EXTERNAL_SEC`

## Executive conclusion

ROUND 13.1 recovered and integrated the previously isolated intelligence code,
completed the bounded SEC/PIT/DeepSeek/SHADOW implementation and passed every
offline engineering, PIT, leakage, authority, quant, and daily regression gate.
It is not READY because `SEC_EDGAR_USER_AGENT` is MISSING in the operator
environment. The fail-closed SEC boundary correctly prevented all live EDGAR
requests. With no real SEC raw corpus, a real DeepSeek filing extraction and
HISTORICAL_PIT_REPLAY acceptance could not truthfully be completed.

No mock documents or fabricated events were used. Classical Quant semantics,
Probability production influence, OperationalPolicy, portfolio/risk logic and
manual-only execution were not changed. ROUND 14 was not started.

## Workspace/writeability self-check

- Initial branch: `codex/round12-operational-advisory-closure`.
- Initial tracked source diff: clean. Known recovery material consisted of the
  Round 13 audit draft and `.codex-temp/round13-recovery/` drafts.
- A minimal tracked README change was applied with `apply_patch`, observed in
  `git diff`, reverted with `apply_patch`, and verified at zero diff.
- No `helper_unknown_error: setup refresh had errors` occurred.
- Result: workspace editing is stable; no workspace-I/O blocker remains.

## Sanitized environment status

- `SEC_EDGAR_USER_AGENT`: `MISSING`
- DeepSeek credential: `PRESENT`
- DeepSeek connectivity: `AVAILABLE`
- Secret values were not printed or persisted.

The only operator action is to set `SEC_EDGAR_USER_AGENT` in the current process
environment to an SEC-compliant identifying organization and contact email, then
rerun the bounded acquisition and acceptance commands.

## Integrated implementation

- Registered the formal command family from `main.py`:
  `intelligence status|acquire|backfill|process|inspect|audit`.
- Added SEC forms 6-K, 20-F, 40-F, DEF 14A, Form 4 and amendments while retaining
  CIK/issuer, accession, accepted/available timestamps, amendment lineage,
  immutable raw hashes, retrieval timestamp and parser/normalization version.
- SEC acquisition remains bounded by CIK/date/max-documents, uses a conservative
  one-request-per-second limiter, retry/backoff, immutable dedup/resume archives
  and an atomic acquisition checkpoint.
- Added strict multi-event extraction with literal source-span verification and
  explicit `unsupported_claim`, `conflicting_evidence`, `low_confidence`, and
  `hallucination_suspected` quarantine states.
- Accepted events are persisted to the canonical intelligence event/evidence
  ledger; quarantined events cannot enter it.
- Added deterministic event-age/half-life decay into the required fifteen
  SHADOW features with cutoff, missing semantics, feature version, event/evidence
  lineage and `production_influence=0`.
- Added formal SHADOW feature persistence and daily AI/PIT fields for provider,
  model, connectivity, new/PIT-eligible/processed documents, calls, cache hits,
  accepted/quarantined events, observations, latest event time, estimated cost
  and production influence. Empty state is `NO_NEW_PIT_DOCUMENTS`.
- Added feature/outcome-separated research assets. The feature build does not
  read outcomes; classical features not supplied to this independent build are
  explicit rather than synthesized. Status is `RESEARCH_LIMITED_SURVIVORSHIP`.

## Quality gates

- Full pytest in the repository-managed Python environment: `920 passed`.
- Focused Round 13.1/SEC/CLI/daily regression: `43 passed`.
- Intelligence, PIT, leakage and daily gate collection: `114 passed`.
- Quant-critical governed regression: `31 passed`, governed count 31.
- Ruff, full repository: PASS.
- Strict mypy, 415 source files: PASS.
- Secret scan: `SECRET_SCAN_PASS`.
- CLI registration/status smoke: PASS.
- Missing SEC User-Agent fail-closed smoke: PASS, exit 2, no request attempted.
- Empty historical replay fail-closed smoke: PASS, exit 3, no data fabricated.
- Empty intelligence audit fail-closed smoke: PASS, exit 3.

An initial full-pytest attempt with the ungoverned system Python failed collection
because that interpreter lacked the declared `exchange_calendars` dependency.
The repository-managed `.venv314` contains it and completed the full 920-test
suite. No dependency or quant code was changed to mask the environment issue.

## Real acceptance counters

| Acceptance item | Actual |
| --- | ---: |
| Raw SEC documents | 0 |
| PIT-certified documents | 0 |
| Real DeepSeek filing calls | 0 |
| Processed SEC documents | 0 |
| Structured events | 0 |
| Accepted evidence-backed events | 0 |
| SHADOW feature observations | 0 |

These counters are intentionally zero because live SEC acquisition was prohibited
by the missing SEC User-Agent. DeepSeek connectivity alone is not acceptance.

## Authority and safety

- LLM production influence: `NONE` / 0.
- LLM cannot alter alpha, probability, target weights, portfolio or risk.
- LLM cannot emit executable BUY/SELL instructions.
- Probability production influence: unchanged.
- OperationalPolicy logic: unchanged.
- `auto_execution=false`.
- `manual_execution_only=true`.
- Classical Quant can run independently; full and quant-critical regressions pass.

## Final disposition

`ROUND13_1_READY` is prohibited because every required real nonzero acceptance
counter is zero. The correct state is:

`ROUND13_1_BLOCKED_EXTERNAL_SEC`

After the operator supplies the one required environment value, rerun a small
CIK canary, bounded backfill, real process, and explicit historical replay. Only
nonzero, immutable, evidence-backed counters plus the already-passing safety
gates may change the verdict to READY.
