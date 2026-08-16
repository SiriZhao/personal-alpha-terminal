# ROUND21 Broad Universe / PIT / Factor Eligibility Closure

Date: 2026-08-14

Verdict: `ROUND21_BLOCKED`

## Baseline

- Branch/commit: `codex/round13` / `dae74ff` (clean before edits).
- Baseline quant-critical: `31 passed`; baseline daily machine evidence was preserved.
- The baseline daily artifact reported 4,966 requested, 18 provider-returned, 9 refreshed, 4,955 cache-reused, and 100% certified coverage while PIT had zero factor-eligible equities.

## Root cause and repaired semantics

Two independent accounting defects were confirmed. The daily certification view used the 18-symbol core matrix as `provider_returned_count` while using the 4,966-symbol manifest as requested population. Its 100% coverage was only `108/108` core certified bars. The terminal now names this scope and separately reports broad provider-response coverage (`9/4966 = 0.18%`) and latest-price coverage (`4964/4966 = 99.96%`).

The batch refresh resume path considered a symbol cache reusable solely because its latest bar reached `end_date`. It did not prove that cached history reached `start_date`; a recently refreshed but factor-insufficient symbol was therefore skipped. The cache contract now requires both stored bounds to span the requested window.

## Current funnel and blocker

The machine artifact is `reports/validation-artifacts/round21_universe_funnel.json`. A current read-only funnel at the daily cutoff found zero visible official-listing records because the latest directory snapshot is not available at that earlier decision timestamp. This is fail-closed, not interpreted as an empty US market. Consequently historical sufficiency/PIT/factor stages are unavailable at that cutoff and no factor candidate can be generated. The legacy snapshot reconciliation is deliberately marked failed because its cache bucket was created before the stricter window contract.

No broad-universe backfill was started from this run: it would require a new immutable directory snapshot visible at the decision time, a window derived from active factor requirements, and a resumed provider run whose terminal buckets reconcile. Those requirements remain the production closure blocker.

## Fixed-cardinality removal

- Removed `portfolio_max_holdings` from active config resolution and `PortfolioConstraints`.
- Removed post-optimizer `MAX_HOLDINGS_EXCEEDED` blocking.
- Removed `universe_candidate_max` and the pre-optimizer ranked candidate cap.
- Legacy config fields are ignored rather than applied; no replacement cardinality is introduced.
- Terminal now states fixed holdings cap `NONE` and that pre-optimizer Top-N / optimizer cardinality caps are `NONE`.
- Stress regression runs 25 symbols without a holdings-count violation while preserving long-only, gross and single-name caps.

## Validation

- Full pytest with workspace-local TEMP: `968 passed` (the initial unscoped run had 196 Windows ACL errors; rerun was clean).
- Final ROUND21 focused tests: `38 passed`.
- quant_critical: `31 passed`.
- Ruff: `PASS`.
- strict mypy: `421 source files, no issues`.
- Secret scan: `SECRET_SCAN_PASS`.
- doctor: PASS with expected `OperationalPolicy IDENTITY_MISMATCH`; no policy was created or renewed.
- final `--no-refresh daily`: DATA `PASS`, PIT `FAIL_BLOCKING`, all downstream recommendation stages `NOT_RUN`; no actions and ledger unchanged.

## Safety and remaining work

LLM remains `SHADOW` with production influence `NONE`; Probability remains fallback classical with weight `0`; Broker API and automatic execution remain disabled. Historical survivorship/PIT research remains not certifiable. This report does not claim production certification or `ROUND21_READY`.
