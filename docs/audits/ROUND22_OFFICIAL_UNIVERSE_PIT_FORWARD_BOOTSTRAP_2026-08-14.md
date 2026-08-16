# ROUND22 Official Universe PIT / Forward Production Bootstrap Closure

Date: 2026-08-14

Verdict: `ROUND22_FORWARD_READY_HISTORICAL_RESEARCH_UNCERTIFIED`

## Answers

1. ROUND22 verdict: `ROUND22_FORWARD_READY_HISTORICAL_RESEARCH_UNCERTIFIED`
2. Current official universe source: `nasdaq_trader_symbol_directory` (Nasdaq Trader current symbol directory)
3. Latest snapshot ID: `512d57d17dcb2ae40fe92dcff26b733c5a6ffaa25d27a84703b0282729364ee6`
4. acquired_at: `2026-08-14T04:15:47.421548+00:00`
5. available_at: same as acquired_at (actual acquisition time)
6. record_count: `8836`
7. Decision-visible snapshot ID (analysis 2026-08-12): `7972f2c66f1e909a6fc34c904c04b2e9e0d836474f9a27a731a3c5ad18240ea7` (8833 records, acquired 2026-08-12T04:14:23Z)
8. Historical snapshots available count: `5` immutable content-addressed snapshots; `historical_membership=False` and `historical_use_allowed=False`
9. Forward bootstrap status: ACTIVE from first decision-visible snapshot; no backdating
10. Historical PIT certification status: `NOT_CERTIFIABLE` / `RESEARCH_LIMITED_SURVIVORSHIP`
11. Current expected analysis session (calendar): `2026-08-13`
12. Actual selected analysis session (no-refresh cache replay): `2026-08-12` (latest completed session in the manifest)
13. Provider requested: `4966`
14. Refreshed: `15`
15. Cache reused: `4949`
16. Quarantine: `1` (SVA)
17. Unresolved: `1` (MDV, NO_PRICE_HISTORY)
18. Latest-price coverage: `4964 / 4966 = 99.96%`
19. Required history sessions: `253` (derived from active factors: momentum 252+1, trend 126, volatility 63+1)
20. History-sufficient count: `4535 / 4956 = 91.51%` (remaining 421 classified NEW_LISTING)
21. PIT eligible count: `3433`
22. Liquidity eligible count: `2132`
23. Factor eligible count: `2132`
24. Alpha-scored count: `2132` factor rows; `1166` alpha-positive
25. Optimizer input count: `1161` (no arbitrary Top-N; full eligible pool)
26. Fixed holdings cap: `NONE` (no `maximum_holdings`, no pre-optimizer Top-N, no optimizer cardinality cap)
27. LLM production influence: `NONE` (deepseek / deepseek-v4-flash / SHADOW)
28. Probability production weight: `0` (PROBABILITY_FALLBACK_CLASSICAL)
29. OperationalPolicy: `IDENTITY_MISMATCH`; not created, renewed, or bypassed
30. Full pytest: `977 passed`
31. quant_critical: `31 passed`
32. Ruff: `PASS`
33. Mypy (strict): `PASS` (421 source files)
34. Secret scan: `SECRET_SCAN_PASS`
35. Git status: uncommitted ROUND21+ROUND22 changes on `codex/round13`; no push/tag/release
36. Commits: none created this round (working tree only)
37. Remaining blockers:
    - Historical survivorship-safe PIT universe remains `NOT_CERTIFIABLE`.
    - `SIGNAL` stays `FAIL_BLOCKING` because strategy production approval (locked OOS / PIT / survivorship / after-cost evidence) is absent.
    - `OperationalPolicy` identity mismatch requires explicit user re-authorization.
    - A live `python main.py daily` refresh attempt did not produce a new completed run file before the shell timeout and was stopped at the interactive prompt; only the no-refresh forward path is claimed as verified this round.
    - `MDV` remains an unresolved provider failure (`NO_PRICE_HISTORY`); `SVA` is quarantined.

## Root cause and changes

- Root cause: `_directory_or_fallback` only read `latest.json`; if the newest snapshot was acquired after the decision time it fell back to the local current master, so no official snapshot was ever decision-visible.
- Fixed: immutable content-addressed snapshots are now selected by the newest `available_at <= directory_cutoff`, with the latest pointer preferred only when it is decision-visible.
- Production directory membership is additionally bounded to the analysis date (`analysis_date 23:59:59Z`), while price PIT continues to use the real decision time; a 2026-08-14 snapshot cannot be used for a 2026-08-12 analysis.
- Completed-session date selection now resolves to the same trading day after close (and the next trading day becomes the execution/trade date); no-refresh cache replay still resolves analysis to the latest completed session in the manifest.
- Required history is derived from active Classical Champion factors (`253` sessions), not a magic constant.
- XNYS session table was backfilled for the required history window with actual-ingestion-time availability; initialization range is now history-aware.
- CLI gained `universe` alias with `status`, `capture`, `audit`, `funnel`, `history-sufficiency`; no duplicate service implementation.

## Safety

- No broker API, no automatic execution, no ledger mutation, no policy creation/renewal, no Alpha/factor changes.
- Manual-only execution preserved; final run produced 0 actions.
