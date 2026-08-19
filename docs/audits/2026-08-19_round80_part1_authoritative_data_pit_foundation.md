# ROUND80 Part 1 — Authoritative Data + PIT Foundation

Date: 2026-08-19
Starting SHA: `0f760bdb7b751a430f09e939f7d5b83db5c58a2a` (ROUND79)
Branch: `feature/agentic-quant-intelligence-round42-51`

## Baseline and inherited state

The pre-change audit found the following inherited, unrelated worktree paths;
they were preserved and are not included in the ROUND80 commit:

- `.gitignore`
- `src/personal_alpha_terminal/quant_engine/alpha_engine2/deflated.py`
- `tests/unit/quant_engine/alpha_engine2/test_shadow_and_deflated.py`
- `tests/unit/test_terminal_cli.py`
- `docs/audits/2026-08-17_FINAL_FLAGSHIP_AUDIT_CLEANUP_STRESS_TEST.md`

The production policy remains `PURE_QUANT`; Probability formal influence is
`0`, LLM is `L1_SHADOW_SCORING` with formal influence `0`, Alpha Engine 3 and
Adaptive Exposure remain challengers, long-only/manual confirmation remains
in force, and automatic broker execution remains disabled.

Existing evidence truth remains unchanged: `BLOCKED_DATA_QUALITY`, with PIT,
survivorship, benchmark, historical tradability, and locked OOS blocked. No
external historical package was fabricated or silently substituted.

## Delivered

### Provider-independent authority boundary

Added `data.authority` contracts for:

- `DataDomain`, `ProviderMetadata`, `ProviderRole`, and `AuthorityTier`;
- `RawObservation`, `CanonicalObservation`, and `DataProvenance`;
- `CoverageReport`, `DataConflict`, and PIT `PITQuery`;
- metadata-only provider registry and per-domain authority resolution;
- conflict detection that preserves disagreements for review instead of
  silently selecting a source.

The default registry explicitly records Yahoo Finance and Stooq as
operational complementary price sources, not certified historical PIT
sources. SEC EDGAR, official exchange evidence, ALFRED, historical
constituents, OpenFIGI, and optional Alpaca roles are declared with explicit
coverage/credential semantics and remain disabled until a legitimate adapter
or immutable import is bound.

### SEC-first PIT normalization

Added `data.authority.sec_edgar` and append-only SQL ledgers for SEC filings,
Company Facts, and lifecycle events. SEC filing acceptance datetime is the
only `known_at`; filing date and local retrieval time are never substituted.
Company Facts require matching accession/form/filing metadata, preserve
revision identity and content hash, and expose only facts with
`known_at <= decision_timestamp`. Later amendments/restatements therefore
cannot leak backward into historical decisions.

SEC `formerNames` metadata is normalized as lifecycle evidence whose
availability is the source snapshot time; its historical effective date is not
used to backdate knowledge.

### Durable identity and lifecycle evidence

Added immutable in-memory PIT identity contracts and a persistence ledger for
issuer/security IDs, CIK anchors, optional FIGI, time-bounded ticker/exchange/
name attributes, confidence, and lifecycle events (listing, delisting,
suspension, ticker/name changes, mergers, acquisitions, spinoffs, splits,
reverse splits, and exchange changes). Ticker reuse and multiple share classes
remain explicit `AMBIGUOUS`/`UNAVAILABLE` outcomes rather than ticker-only
joins.

### Operator and failure-path surfaces

- `python main.py data-authority --json` provides a local, machine-readable
  source-authority posture without network calls and explicitly says that it
  is not historical certification.
- Migration failures now fail closed with the operation and redacted absolute
  target path, without dumping SQL or credentials.
- The new migration `b7e0a2d4c5f6` creates lifecycle, SEC filing, and SEC
  Company Facts evidence tables. It upgraded a fresh temporary SQLite database
  through `head` successfully.

## Verification evidence

| Check | Result |
| --- | --- |
| ROUND80 focused authority/migration/CLI tests | 13 passed in the latest run |
| Broader SEC/PIT/ROUND74/ROUND79 focused bundle | 52 passed in the measured run |
| Ruff (task-owned source/tests) | PASS |
| Strict mypy (9 touched modules) | PASS |
| Secret scan | `SECRET_SCAN_PASS` |
| Git diff check | PASS |
| Fresh temporary SQLite migration to head | PASS (`b7e0a2d4c5f6`) |
| Normal terminal first startup | 5.127 s, exit 0 |
| Normal terminal immediate second startup | 4.933 s, exit 0 |
| `--no-refresh daily` local frame | 4.969 s; frame rendered, cached advice non-actionable; managed ACL then blocked migration |
| Doctor diagnostic under managed ACL | 6.121 s; precise `operation=alembic-upgrade` path/error, exit 2 |

The existing managed Windows ACL denies writes to the production `var`/report
paths. This is classified as an environment/runtime limitation, not converted
into a certification or product PASS. No database relocation or stale advice
promotion occurred.

## Current authority/certification status

| Domain | Current status | Reason |
| --- | --- | --- |
| operational market prices | `PARTIAL` | Yahoo/Stooq are enabled operational sources; no certified historical PIT vintage |
| corporate actions / total return | `BLOCKED_WITH_EVIDENCE` | no enabled PIT-capable immutable package |
| issuer/security identity | `BLOCKED_WITH_EVIDENCE` | no complete historical permanent-ID package bound |
| lifecycle / membership / delistings | `BLOCKED_WITH_EVIDENCE` | no complete historical lifecycle/constituent import |
| benchmark | `BLOCKED_WITH_EVIDENCE` | no aligned PIT benchmark package |
| fundamentals / filings / events | `BLOCKED_WITH_EVIDENCE` | SEC schemas and adapter exist; complete imported vintages are not bound |
| executable opens / tradability | `BLOCKED_WITH_EVIDENCE` | no complete historical executable-open/status evidence |
| locked OOS | `BLOCKED_DATA_QUALITY` | no sealed immutable external dataset/manifest |

Credential presence was checked status-only: `SEC_EDGAR_USER_AGENT=PRESENT`,
`OPENFIGI_API_KEY=MISSING`, and optional Alpaca credentials `MISSING`. Presence
of the SEC user agent does not establish coverage or certification.

## Exact remaining blockers

1. Bind a legally obtained immutable historical package covering permanent IDs,
   ticker/lifecycle history, constituents, delistings and returns, raw PIT
   OHLCV, corporate actions/total-return vintages, aligned benchmarks,
   timestamped SEC fundamentals/filings/events, and executable next-session
   opens/trading status.
2. Import and audit the package through the new provenance/revision ledgers;
   missing critical fields must remain missing and block certification.
3. Seal a locked-OOS manifest only after the imported package passes the
   existing PIT/survivorship/tradability gates.

No Quant, Probability, LLM, Alpha Engine 3, or Adaptive Exposure production
authority was promoted. No Alpha Engine 4 was created.

## Part 1 verdict

**ROUND80 PART 1: ENGINEERING PASS WITH DATA CERTIFICATION BLOCKED.**

The authoritative-data/PIT architecture and fail-closed provenance gates are
implemented and tested. Genuine historical certification remains blocked until
the exact external evidence package above is legitimately imported.
