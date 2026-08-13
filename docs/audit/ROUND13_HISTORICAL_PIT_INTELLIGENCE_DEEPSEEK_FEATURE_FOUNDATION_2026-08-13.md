# ROUND 13 Historical PIT Intelligence / DeepSeek Feature Foundation

Date: 2026-08-13

Verdict: `ROUND13_BLOCKED`

## Executive conclusion

ROUND 13 is not ready. The repository already contains a meaningful SEC/PIT and
LLM intelligence foundation, but there is no completed production-facing
`intelligence` CLI workflow and no accepted real SEC -> DeepSeek -> structured
event -> shadow-feature run. No documents, events, LLM responses, or historical
research evidence were fabricated to obtain a READY verdict.

The Classical Quant Core was not changed. LLM production influence remains
`NONE`; automatic execution remains disabled and broker execution remains manual.

## Confirmed existing foundation

- SEC EDGAR acquisition uses official submissions/archive endpoints, a required
  compliant User-Agent, rate limiting, retry/backoff, immutable raw landing-zone
  hashes, resumable acquisition, and corruption verification.
- SEC PIT availability uses the official accepted timestamp. A filing without a
  confirmed acceptance time cannot enter the certified corpus.
- RawInformation implements immutable source hashing and
  `available_at <= decision_as_of` visibility.
- Amendments retain a separate revision identity and link to the latest matching
  prior original filing.
- Historical CIK/ticker mapping rejects current-only snapshots and requires a
  historical timeline source identity.
- Extraction cache identity includes raw content hash, model, and prompt version.
- The canonical LLM gateway persists hashes, tokens, latency, retries, validation
  status and estimated cost, but not credentials or raw prompt bodies.
- Existing event artifacts require evidence and enforce future-evidence exclusion
  for BACKTEST_SAFE status.
- Existing LLM event factor observations are SHADOW and cannot affect production
  without a statistical probability and an explicit production approval artifact.
- Runtime configuration locks `intelligence_max_ai_contribution` to zero.
- LLM runtime enforces `production_influence=NONE`.

## Gaps against ROUND 13 completion

- No `python main.py intelligence status|acquire|backfill|process|inspect|audit`
  command family is registered.
- The current SEC form allow-list covers 10-K, 10-Q, 8-K and amendments, but does
  not yet include 6-K, 20-F, 40-F, DEF 14A or Form 4.
- Current extraction returns a single broad event schema; it does not yet enforce
  the requested per-event literal source span, unsupported-claim states, complete
  Round 13 taxonomy, or multi-event filing output.
- Only a single `llm_event_intensity` SHADOW factor exists; the requested
  deterministic multi-feature transform and explicit temporal decay are absent.
- There is no finalized operational/research corpus status and acquisition
  checkpoint CLI.
- No Round 14 feature/outcome-separated dataset has been generated.
- Daily still reports zero processed documents, PIT events and shadow-factor
  observations.

## Environment blockers

1. `SEC_EDGAR_USER_AGENT` is not configured. Official SEC acquisition must not be
   attempted without a compliant identifying User-Agent. Therefore real SEC
   acquisition is `BLOCKED_EXTERNAL_SEC_DATA` in this environment.
2. The Codex Windows file sandbox repeatedly failed while reading existing files
   for `apply_patch` with `helper_unknown_error: setup refresh had errors`.
   New isolated draft files could be created, but existing acquisition/CLI files
   could not be safely updated. Unintegrated drafts were moved to
   `.codex-temp/round13-recovery/`; the tracked source tree was restored clean.

DeepSeek itself is available and sanitized status reports:

- provider: deepseek
- model: deepseek-v4-flash
- connectivity: AVAILABLE
- credential: PRESENT
- production influence: NONE

No real document extraction call was made because there was no newly acquired,
PIT-certified SEC corpus eligible for the guarded processing path.

## Verification evidence

- Focused existing SEC/PIT/LLM tests: `50 passed in 2.26s`.
- Tests covered accepted timestamp PIT, future revision exclusion, amendments,
  immutable raw checksums, resumable acquisition, historical CIK mapping,
  extraction cache identity, LLM runtime, budgets and extraction agents.
- Worktree was clean after recovery; no strategy/config identity changed.

## Safety status

- Classical Quant Core behavior: unchanged.
- LLM direct BUY/SELL/HOLD authority: none.
- LLM alpha/target-weight authority: none.
- LLM calibrated probability authority: none.
- LLM production influence: `NONE / 0`.
- Automatic broker execution: disabled.
- Manual execution boundary: unchanged.
- Secret persistence: none observed; credential values were never printed.

## Required next steps

1. Configure a compliant `SEC_EDGAR_USER_AGENT` value outside version control.
2. Restore reliable Codex workspace editing for existing files.
3. Integrate and review the recovered Round 13 contracts/extraction/CLI drafts.
4. Add the expanded SEC form taxonomy, strict evidence-span validation,
   deterministic multi-feature decay, database persistence and CLI tests.
5. Run real SEC acquisition, real DeepSeek extraction and explicit
   `HISTORICAL_PIT_REPLAY` acceptance.
6. Run the full pytest, ruff, strict mypy, secret, PIT, leakage, quant and daily
   gates before reconsidering the verdict.
