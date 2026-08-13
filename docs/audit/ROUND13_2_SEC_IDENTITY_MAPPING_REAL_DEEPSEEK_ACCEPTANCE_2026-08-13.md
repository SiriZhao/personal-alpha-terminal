# ROUND 13.2 - SEC Identity Mapping & Real DeepSeek Acceptance Closure

Date: 2026-08-13

Verdict: `ROUND13_2_READY`

## Executive conclusion

ROUND 13.2 resolved the `SEC_SECURITY_MAPPING_MISSING` blocker without
hard-coding `320193 -> AAPL` and without creating a second security master. A
canonical `issuer_security_identity_history` store now resolves CIK to issuer
and issuer to `security_master` security at an exact PIT cutoff. Acquisition
persists immutable raw documents to the database even when security mapping is
not yet available. Real SEC acquisition, real DeepSeek extraction, literal
evidence validation, SHADOW feature generation, historical PIT replay, daily
integration, and all quality gates completed successfully.

Classical Quant Core, Factor/Alpha/Portfolio/Risk semantics, Probability
production influence, OperationalPolicy, and manual-only execution were not
modified. LLM production influence remains `NONE` / `0`.

## Root cause

- `_acquire` wrote only the landing zone; database raw persistence happened
  later in `process`.
- The CLI default mapping path was `config/cik-mapping.json`, which did not
  exist, so every real acquisition was `ACQUIRED_NOT_FULLY_MAPPED`.
- The live database had no CIK/issuer identity history.
- RawInformation could not represent issuer resolution or security mapping
  status separately.

## Implemented canonical identity layer

- Added `issuer_security_identity_history`, a PIT identity extension of the
  existing `security_master`.
- Added `IssuerIdentityResolver` with CIK -> issuer -> security resolution,
  `effective_from/effective_to`, `available_at`, source, source version, and
  explicit statuses for mapped, missing, ambiguous, delisted, and future
  mapping exclusion.
- Added generic SEC filing identity extraction from `dei:TradingSymbol` and
  Form 4 issuer/ticker evidence. This is not an Apple special case and is not a
  current ticker snapshot passed off as history.
- Added `intelligence identity import-filings` to seed the canonical store.
- Kept `--mapping` as an explicit research/import override; the normal workflow
  now uses the canonical database resolver.
- Added raw database identity columns and `upsert_raw` so raw persistence
  survives unmapped or later-remapped states.
- Changed DeepSeek events so an LLM-provided ticker is only used when the
  canonical security mapping exists. Unmapped events remain issuer-level and
  cannot create ticker/security SHADOW features.

## Real SEC acceptance

- `SEC_EDGAR_USER_AGENT`: `PRESENT` (value not printed).
- Bounded canary `round13-2-aapl-canary`: acquired 2 real documents, mapped 2.
- Expanded mapped canary `round13-2-aapl-canary-wide-mapped`: acquired 20 real
  documents, mapped 20.
- Landing-zone unique raw documents: 44.
- Database raw documents: 44.
- PIT-certified documents: 44.
- Issuer-resolved documents: 44.
- Security-mapped documents: 24 (the 2025/2026 identity-covered subset; older
  broad backfill rows remain correctly unmapped until evidence exists).

## Real DeepSeek acceptance

- Provider: `deepseek`
- Model: `deepseek-v4-flash`
- Incremental real process: 10 documents, 10 real LLM calls, 10 accepted
  evidence-backed events, 15 SHADOW feature rows.
- Historical PIT replay at `2025-05-01T00:00:00+00:00`: 20 processed documents,
  9 real LLM calls on the final replay run, 11 cache hits, 18 accepted events,
  22 quarantined events, 15 SHADOW feature rows.
- Literal evidence-span validation was not weakened; unsupported and
  hallucination-suspected events were rejected.

## Replay and audit

- `intelligence audit` passed:
  - raw landing-zone immutability and checksums
  - PIT acceptance timestamp
  - issuer identity and security mapping source
  - DeepSeek response lineage, model, and prompt version
  - literal evidence-span hash
  - future leakage at replay cutoff
  - production influence none
- Replay result is immutable in `var/intelligence/sec-edgar/processed/` and in
  the `intelligence_research_results` database ledger.

## Daily integration

`python main.py daily` completed successfully. The AI/PIT panel showed:

- Raw SEC documents: 44
- Issuer-resolved documents: 44
- Security-mapped documents: 24
- LLM calls: 10 (latest incremental evidence)
- Processed documents: 10
- Accepted events: 10
- SHADOW observations: 30
- Production influence: NO
- LLM status: SHADOW / PASS_DEGRADED
- Classical pipeline: PASS, provisional manual review only

## Quality gates

- Full pytest: `930 passed`
- Quant-critical regression: `31 passed`
- Focused SEC/identity/intelligence tests: passed, including 10 new canonical
  identity tests
- Ruff: `PASS`
- Strict mypy: `PASS` (416 source files)
- Secret scan: `SECRET_SCAN_PASS`

## Environment note

The real DeepSeek provider required the already-declared `openai` SDK in
`.venv314`; it was installed from the project's `ai` extra. No provider logic
or quant code was changed to accommodate this.

## Final disposition

`ROUND13_2_READY`
