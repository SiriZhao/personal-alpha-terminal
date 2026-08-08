# Terminal Data Stabilization

状态：Implemented and tested for local deterministic workflows; live data certification remains incomplete.

## Product path

`main.py` now starts the Rich terminal Daily Mode. The Streamlit entry remains only for development compatibility. The default path never opens a browser and never connects to a broker.

Daily Mode uses:

```text
Provider chain
-> raw schema validation
-> canonical UTC/ET daily bars
-> provider reconciliation
-> immutable local cache and lineage
-> data quality score and safety gate
-> existing Quant/Portfolio/Risk approval chain
-> Today brief and action list
-> human review
-> manual Charles Schwab fill recording
```

Yahoo is the primary free research source. Stooq is a secondary US stock/ETF history source. The provider list is ordered and extensible; one source failing degrades the run instead of crashing it. If all sources fail, a fresh cache may be retained with an explicit `cached` status. Stale or unsafe data blocks executable actions.

## Safety rules

- Missing prices remain null; zero and previous-close substitution are forbidden.
- OHLC envelope violations, duplicates, future bars, unexplained spikes, stale bars and excessive provider disagreement fail closed.
- Free-provider adjusted-close snapshots are not PIT corporate-action ledgers. Without explicit corporate-action certification, the data snapshot remains `PARTIAL/RESEARCH_ONLY`.
- UTC is the internal clock. US market sessions use `America/New_York` and exchange calendars, including DST, holidays and early closes.
- Nasdaq 23H support is configuration-gated. The 21:00 ET session maps to the next trade date; Friday/Saturday nights and holiday eves remain closed. Night data is optional and information-only.
- AI may explain an existing deterministic result but cannot change symbols, actions, target weights or risk vetoes.

## Validation on 2026-08-08

- Ruff: PASS.
- Mypy: PASS, 56 relevant source files.
- `pip check`: PASS.
- Pytest excluding the sandbox-blocked PostgreSQL ACL group: 478 passed.
- PostgreSQL backup group: 4 passed; 3 blocked by the restricted Windows test token after the test deliberately hardens file ACLs.
- VectorBT/Backtrader group: 4 passed with `NUMBA_DISABLE_JIT=1`; this changes compilation behavior only, not expected calculations.
- Terminal doctor smoke test: PASS; Yahoo and Stooq adapters loaded, broker API absent, Night execution disabled.
- A read-only report directory no longer crashes Today: the analysis remains visible and the unsaved report is reported explicitly.

No live Provider certification was claimed. Real multi-source price comparison, PIT corporate actions, historical-universe certification and an independent Windows packaging test remain release-gate work.
