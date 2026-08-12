# DeepSeek Historical Replay Report

Date: 2026-08-12

Result: **NOT_CERTIFIABLE**

No production historical DeepSeek replay was run because no certified historical
text/event corpus exists.

## 1. Environment

`DEEPSEEK_API_KEY_PRESENT=true`

The key is inherited from the process environment. No key value was written to
source, logs, fixtures, reports, or artifacts.

## 2. Existing LLM Foundation

The project continues to use:

- `LLMProvider`
- `LLMGateway`
- `LLMRouter`
- `PromptRegistry`
- `ModelRegistry`
- immutable extraction cache
- `LLMUsageLedger`

## 3. Structured Intelligence

LLM output must:

- be strict JSON
- pass Pydantic validation
- produce typed `UnifiedEvent`
- preserve source evidence
- keep extraction confidence separate from return probability

Free-text LLM output is never used as a factor.

## 4. Historical Replay

`HistoricalAIReplay` now tracks:

- visible document IDs
- visible document versions
- visible event IDs
- factor observations
- replay hash

Each visible document version is represented as:

`document_id|revision_id|raw_id`

Replay hash includes only documents and evidence available at the cutoff.

## 5. Tests

Automated coverage includes:

- future document exclusion
- future revision exclusion
- same document multi-version replay
- timezone awareness
- missing timezone fail-closed
- malformed payload rejection
- duplicate detection
- symbol mapping
- prompt-injection boundary in extraction prompts
- malformed LLM JSON
- cache identity
- model/prompt version change
- DeepSeek unavailable fallback

## 6. No Real Replay Evidence

The real corpus is empty. No SEC filing, earnings release, transcript,
announcement, or news package is certified.

Therefore:

- source certification: `NOT_CERTIFIABLE`
- extraction coverage: `0%`
- replay status: `NOT_RUN_ON_REAL_CORPUS`
- LLM factor production status: unchanged `SHADOW`
- Champion/Challenger: not run in this round

## 7. Verification

- Ruff: `PASS`
- strict mypy: `PASS`, 368 source files
- pytest: `680 passed`
- secret scan: to be rerun after docs
- synthetic `TEST_ONLY` corpus runner: `PIT_TEXT_CERTIFIED` on controlled fixture

Fixture replay is not production research evidence.

## 8. Round 2.5B Update

DeepSeek historical extraction is still **not run** on a real SEC corpus.

The new SEC EDGAR acquisition runner is implemented and fail-closed:

- `SEC_USER_AGENT` is required before any official SEC request
- immutable raw filing payloads are preserved
- CIK mapping must be sourced from a certified market research dataset
- corpus certification must pass before replay

Current environment state:

- `SEC_USER_AGENT`: not inherited
- real SEC documents: `0`
- corpus certification: `NOT_CERTIFIABLE`
- replay on real corpus: `NOT_RUN`
- LLM feature production status: unchanged `SHADOW`

## 9. Round 2.5B Extension

DeepSeek replay validation on real SEC data remains:

`NOT_RUN`

New SEC infrastructure supports:

- Stage 1 `ACQUIRED_NOT_FULLY_MAPPED`
- per-filing immutable metadata
- amendment/revision PIT visibility
- mapping-pending corpus certification

Because no certified corpus exists, no DeepSeek extraction budget was consumed.
