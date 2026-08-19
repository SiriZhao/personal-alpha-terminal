# ROUND80 — Authoritative Data / PIT / OOS / Performance Closure

Date: 2026-08-19. Scope is data authority, PIT/provenance, survivorship/return/OOS gates, and terminal performance. No alpha model, factor, optimizer, risk, cost, benchmark, universe, production policy, broker, or execution authority changed.

## A. Baseline and safeguards

- ROUND79 final SHA: `0f760bd`; ROUND80 Part 1 start: `f87c9b550e9ff6bd8955f7b049552c27ec57066c`.
- Preserved inherited unstaged paths: `.gitignore`, Alpha Engine 2 deflated module/test, `tests/unit/test_terminal_cli.py`, and the 2026-08-17 audit.
- Production remains `PURE_QUANT` / `PRODUCTION_CHAMPION_UNCHANGED`; Probability is 0% formal influence; LLM is `L1_SHADOW_SCORING` / 0%; Alpha Engine 3 and Adaptive Exposure remain challenger/shadow.
- Long-only/manual confirmation/`AUTO_EXECUTION=DISABLED`/no broker orders/no fixed Top-N/no holdings cap are unchanged.

## B. Architecture

Part 1 supplies the provider-independent authority/PIT core, SEC acceptance-time facts, durable identity/lifecycle contracts and append-only SEC/lifecycle ledgers (`b7e0a2d4c5f6`). Part 2/3 adds:

- cutoff-visible investable universe with `CERTIFIED`/`RESEARCH_GRADE`/`PARTIAL`/`BLOCKED` grades and explicit exclusions;
- PIT SP500/NASDAQ100 constituent import contract and append-only ledger, separated from the production broad universe;
- canonical corporate-action timing, raw/adjusted/total-return semantics and material conflict blocks;
- PIT benchmark/session audit, next-session open evidence audit, ALFRED-style macro vintages, provider health states, and durable conflict records;
- content-addressed raw fetch receipts and immutable dataset snapshots;
- snapshot/factor/portfolio/risk/cost/benchmark/Git-bound locked-OOS manifest fields; an unbound legacy manifest cannot seal;
- new append-only ledger migration `c8d3e7f1a4b6` for raw fetches, snapshots, historical constituents, and conflicts.

The Part 2 evidence layer is not imported during normal fast start. Ingestion/normalization/replay remain background or explicit paths.

## C. Providers and quality posture

`python main.py data-authority --json` made no remote calls and produced 13 domain audits.

| Provider | Role/domains | PIT | Credential | State |
| --- | --- | --- | --- | --- |
| Yahoo Finance | PRIMARY prices/benchmark | no | no | DEGRADED (local declaration only) |
| Stooq | SECONDARY prices/benchmark | no | no | DEGRADED (local declaration only) |
| SEC EDGAR | OFFICIAL filings/fundamentals/identity | yes | SEC user-agent | AUTH_REQUIRED; adapter disabled pending configured import |
| Official exchange evidence | lifecycle/actions/executable opens | yes | no | DISABLED/import required |
| Historical constituents import | membership | yes | no | DISABLED/import required |
| FRED/ALFRED | macro/risk-free | yes | no | DISABLED/adapter required |
| OpenFIGI | identity cross-check | no | yes | AUTH_REQUIRED |
| Alpaca optional | open cross-check | no | yes | AUTH_REQUIRED |

No provider was promoted to production authority. Promotion still requires schema/timestamp/PIT validation, coverage, reconciliation, deterministic replay, provenance, and a passing authority gate.

## D. Identity, survivorship, filings, actions, returns

- CIK/internal issuer/security identity is primary; ticker is only a time-bounded attribute. Rename, reuse, share-class ambiguity, validity and former-name PIT semantics are tested.
- Lifecycle supports listing, delisting, suspension, ticker/name change, merger/acquisition/spinoff, split/reverse split and exchange change.
- SEC facts use acceptance `known_at`; future filing/restatement evidence is rejected before its public timestamp.
- Raw OHLCV is distinct from provider-adjusted and reconstructed PIT total return. Reconciliation has `MATCH`, `WITHIN_TOLERANCE`, `MATERIAL_CONFLICT`, and `MISSING_SECONDARY`; no provider is picked because it improves a backtest.
- Benchmark audit blocks semantic/session mismatch. Next-open audit blocks same-session fills, bad prices/volume, halts, unresolved symbol changes, and benchmark-session mismatch.
- Fixture semantics are complete, but real external coverage is not: no certified full US security master/ticker history/listing/delisting/delisting-return package, corporate-action/total-return vintage package, aligned benchmark package, or consolidated executable-open history is present.

## E. Snapshot, OOS, and forward evidence

Snapshots bind provider versions, raw/normalized hashes, security master, corporate action, benchmark, fundamental, universe, schema, normalization, cutoff, and Git SHA. Raw fetch receipts retain logical request, timing, source timestamp, content hash and storage reference.

Current truth:

- data certification: `BLOCKED_DATA_QUALITY`;
- locked OOS: manifest missing / `BLOCKED_DATA_QUALITY`;
- forward shadow: `0/120` paired observations and `0/40` independent sessions.

No historical replay/walk-forward/pseudo-OOS was relabelled as locked OOS and no future evidence was fabricated.

## F. Terminal P0 performance

Root cause measured using `-X importtime`: terminal CLI eagerly imported Round7/8/9, broad-universe, forward-shadow and canonical configuration, transitively loading pandas/scipy/sklearn/historical research before shell rendering. The fix makes command handlers/configuration lazy and adds a read-only fast-start config for only `report_dir`, DB identity and config hash. Explicit refresh still loads the full canonical config in Phase B. `--no-refresh daily` is now local diagnostic only and never actionable.

| Metric | Before | After | Delta |
| --- | ---: | ---: | ---: |
| Cumulative CLI import | 14.348s | 0.789s | -13.559s |
| Normal shell (ACL-degraded) | 15.529s | 1.198s | -14.331s |
| `--no-refresh daily` | 14.035s + readonly DB failure | 1.192s, exit 0 | -12.843s |
| Isolated first startup | N/A | 6.878s | <=10s |
| Immediate second startup | N/A | 1.559s | <=5s |
| No-new-session startup | N/A | 1.529s | <=5s |
| Local fast snapshot | N/A | 0.070–0.072s | measured |
| Foreground fast-start work | N/A | 1.077–1.079s | measured |
| Fatal DB doctor diagnostic | 28.158s | 1.169s | -26.989s |

The 6.878s isolated first start includes fresh Python bytecode-cache population. Import profiling after the fix shows no pandas/scipy/sklearn/historical research package on the local no-refresh path. Warm starts made zero provider requests and launched no historical rebuild.

The normal shell remains non-actionable. A non-writable default runtime directory fails fast with exact `REFRESH_STATE_PERMISSION_ERROR`; no DB relocation occurs. `doctor` now performs `BEGIN IMMEDIATE; CREATE TABLE; ROLLBACK` under one SQLite transaction before migrations. It failed in 1.169s on the real DB with the exact readonly path/operation; the probe table is rolled back.

## G. Validation

- New migration applied successfully to a fresh temporary SQLite DB; all four new authority ledger tables exist.
- Ruff: pass on ROUND80-touched source/tests.
- Strict mypy: pass on authority foundation, repository, models, locked OOS, fast start and CLI.
- Secret scan: `SECRET_SCAN_PASS`.
- Focused authority/terminal pytest: 20/20 assertions printed `PASSED`.
- Existing authority + locked-OOS + production parity pytest: 26/26 printed `PASSED`.
- Quant-critical suite: 6/6 printed `PASSED`.

Managed Windows/Python 3.14 pytest processes did not exit after selected assertions completed, even with temporary roots, redirected bytecode cache, and third-party plugin autoload disabled. They were interrupted only after all listed assertions printed `PASSED`; therefore this is not claimed as a clean pytest exit or a full-pytest PASS.

Real entrypoints: `main.py`, `main.py --no-refresh daily`, `data-evidence`, `alpha-engine3-reality`, `adaptive-exposure`, `data-authority --json`, and `locked-oos --json` completed safely. `doctor`, `forward-shadow readiness`, and `forward-shadow status --json` exposed the same real SQLite write ACL. No fallback database was created.

## H. Final matrix

| Area | Status | Main evidence/blocker |
| --- | --- | --- |
| DATA_AUTHORITY | PASS_WITH_WARNINGS | independent registry/contracts; package absent |
| SEC_PIT_FUNDAMENTALS | RESEARCH_GRADE | acceptance-time semantics; no external backfill |
| SECURITY_MASTER | PASS_WITH_WARNINGS | durable identity semantics; coverage incomplete |
| TICKER_HISTORY | RESEARCH_GRADE | rename/reuse/share-class tested; coverage incomplete |
| LISTING_HISTORY | PARTIAL | import/lifecycle path; no full US import |
| DELISTING_HISTORY | PARTIAL | no complete history/terminal returns |
| SURVIVORSHIP_SAFETY | BLOCKED_WITH_EVIDENCE | membership/delisting-return package absent |
| CORPORATE_ACTIONS | RESEARCH_GRADE | PIT contracts; coverage absent |
| TOTAL_RETURN | RESEARCH_GRADE | reconstruction/conflict gate; certified series absent |
| BENCHMARK | PARTIAL | semantic audit; Yahoo/Stooq not PIT total-return evidence |
| EXECUTABLE_OPEN | RESEARCH_GRADE | legal open contract; consolidated history absent |
| INDEX_CONSTITUENTS | PARTIAL | SP500/NASDAQ100 import interface; history absent |
| LOCKED_OOS | NOT_MATURE | certified snapshot/package and sealed manifest absent |
| FORWARD_EVIDENCE | NOT_MATURE | 0 paired / 0 sessions |
| TERMINAL_PERFORMANCE | PASS | shell decoupled and <=10s |
| REPRODUCIBILITY | PASS_WITH_WARNINGS | append-only hashes/manifests; external package absent |
| PRODUCTION_SAFETY | PASS | manual-only/zero LLM+Probability influence preserved |

## I. Remaining blockers and verdict

1. Repair ACLs for `var/personal_alpha.db`, `var/`, `reports/`, and default runtime-state directory; do not relocate/recreate the production DB silently.
2. Import a legitimate immutable historical package for permanent IDs/ticker history, membership/listing/delisting/delisting returns, PIT actions/returns, benchmark, fundamentals/events and executable opens.
3. Complete coverage/reconciliation before provider promotion.
4. Seal a new snapshot-bound OOS protocol only after certified data exists.
5. Accumulate real forward observations; do not synthesize `120/40` gates.

**ROUND80 verdict: `PASS_WITH_WARNINGS` for infrastructure and terminal P0 closure. Historical economic evidence, survivorship certification, executable-open coverage, locked OOS and forward sample remain honestly blocked/not mature. No production promotion is supported.**
