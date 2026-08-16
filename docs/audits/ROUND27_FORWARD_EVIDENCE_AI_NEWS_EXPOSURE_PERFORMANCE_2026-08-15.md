# ROUND27 — Forward Evidence / AI / News / Exposure / Performance

## Verdict

`ROUND27_READY_FORWARD_VALIDATION`.

The acceptance run is `daily-2420c68452d142298e6b42482341391f` and is pinned by `round27_acceptance_manifest.json`.  Its classification is `VALID_ANALYSIS_ACTIONABLE_PROVISIONAL`, not research certification.  Automatic execution and broker API remain disabled; every action remains manual Schwab review.  AI, news, ETF research, and probability have no trade authority.

## Frozen baseline and decision integrity

- ROUND27 baseline: `var/backups/round27-baseline-20260815T181656Z`.
- Baseline HEAD / branch: `7dce2e5418803d73d26da86ea2a4171ed9dd94e4` / `codex/round25etf`.
- ROUND26 slow comparison run: `daily-057d6c4206ab4dc39f4dbb564f89c812` (DATA 272.5856s; total 436.5018s).
- Acceptance DecisionManifest semantic hash: `def9b6be383088f6dc6d88308cc80623c5733f710aa98fbbe95cf589d246d16b`.
- Deterministic replay, future-leakage, and semantic-isolation gates passed.  Optimizer input count was 1,171; there is no fixed holdings cap, no pre-optimizer Top-N, and the optimizer received the complete eligible set.
- Formal actions: ten BUY proposals — ATEX, CDNA, DK, LQDA, RLAY, RVMD, STX, TVTX, UMC, VSTS.  Live ledger remains NAV $100,000, cash $100,000, invested 0%; targets were not written as actual holdings.

## Forward probability evidence

`reports/validation-artifacts/forward_prediction_audit.json` preserves the original append-only ledger and adds a reversible canonical projection.

- Raw prediction rows: 90.
- Canonical predictions: 26; duplicate rows: 64.
- Matured canonical outcomes / effective N / decision-date N: 0 / 0 / 0.
- Primary horizon: 21 sessions; promotion: `NOT_ELIGIBLE`; production influence: 0%.
- The index migration does not delete or rewrite historical rows.  It repairs only early records whose wall-clock report time was incorrectly recorded as the decision cutoff, using the immutable DecisionManifest PIT cutoff.  Future records use the certified cutoff and a content-derived market-input semantic hash; reruns become occurrences rather than OOS observations.
- REPLAY, TEST, DEBUG, VALIDATION, BACKFILL, and REPORT_ONLY are rejected by the ledger.  Test snapshot roots are isolated from the production ledger.

## DeepSeek and grounded news

Acceptance used live `deepseek-v4-flash`: 4 calls, 20,043 prompt tokens, 3,159 completion tokens, 25.848s API latency.  `AI_STATUS=PASS`, source `DEEPSEEK_STRUCTURED_V3`, semantic grounding `AI_SEMANTIC_GROUNDING_OK`, DeepSeek sections 5/5, fallback sections 0, whole fallback false.

- Per-pass diagnostics retain raw/parsed/schema/semantic/latency/token/error evidence without keys. PASS4 only synthesizes verified facts and cannot regenerate formal action, cash, weight, cost, or probability facts.
- Official-news intake: 60 raw rows, 60 normalized rows, 60 persisted clusters, and 60 pre-decision rows; 12 complete Tier-1 BLS items were displayed and supplied to the brief. Post-decision/pre-execution, post-execution, and unknown-timestamp counts were 0 for this run.
- `source_count=None` visible: 0; fabricated visible news: 0.  General-news configuration is independent of official-macro intake.

## Current operational exposure

The current-only exposure artifact is `reports/daily-runs/daily-2420c68452d142298e6b42482341391f/current_exposure.json`. It is explicitly excluded from historical PIT and historical neutralization.

- Formal size coverage: 100% (10/10); optimizer-candidate size coverage remains unavailable/0% because no historical market-cap field is invented.
- Formal sector coverage: 100% (10/10) from SEC current SIC; candidate sector coverage is unavailable/0%.
- Unknown formal size weight: 0%; unknown formal sector weight: 0%.
- Top sector: MANUFACTURING; sector HHI: 0.52.
- Current caps use provider-reported Yahoo market cap first, then verified current shares × current price, otherwise UNKNOWN. All evidence is marked `CURRENT_ONLY` with timestamps and provenance.

## Performance and validation

Stage Profiler V2 for the acceptance run: DATA core 127.6043s; market-data network 57.5832s; news network 3.3151s; LLM network 25.848s; DATA total 185.1874s; total wall clock 319.9453s.  Compared to the ROUND26 slow run, DATA improved 87.3982s (32.06%) and total wall clock improved 116.5565s (26.70%).  DB query regression is explicitly `UNAVAILABLE`, not guessed. See `reports/validation-artifacts/performance_diff.json`.

- pytest: 1,172 passed (two unrelated SQLite adapter deprecation warnings).
- quant-critical: 31 passed; quant regression: 10 passed; leakage/semantic isolation: 20 passed.
- Ruff: PASS; Mypy strict: PASS (464 files); secret scan: PASS.

## Remaining limits

Research certification remains `NOT_CERTIFIABLE`; probability has no mature evidence and no production effect. Candidate-universe current size and sector coverage remain intentionally unavailable rather than estimated. Current operational exposure is a next-trade risk diagnostic only, not historical research data.

## Repository state

`git diff --check` passed. The ROUND27 implementation and audit artifacts are intentionally uncommitted at handoff; no new commit was created. The working tree contains the ROUND27 source, tests, acceptance manifest, and audit report listed above.
