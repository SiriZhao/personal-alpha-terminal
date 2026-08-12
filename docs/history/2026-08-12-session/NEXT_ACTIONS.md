# Next Actions

Date: 2026-08-12

Only real remaining work is listed. No item is marked complete because a live
run, script, or report exists; completion requires the corresponding artifact
and certification evidence.

## P0 Blocking

1. Acquire a licensed or user-supplied survivorship-safe historical US equity
   dataset with permanent security identifiers, ticker vintages, listing and
   delisting lifecycle, delisting returns, historical membership, PIT corporate
   actions, PIT total-return vintages, calendar, and SPY/QQQ benchmark history.
2. Build the provider adapter acceptance audit for that dataset and certify it
   through the existing `research_dataset` and acquisition contracts.
3. Certify a historical text/event corpus (SEC filings, earnings releases,
   transcripts, company announcements, news, or event feeds) with immutable raw
   payload hashes, availability timestamps, source identities, symbol mapping,
   timezone, duplicate handling, restatement handling, and replay safety.
4. Freeze the 252+ session locked-OOS definition before any final parameter or
   feature tuning. Do not open or inspect it until all upstream data is
   certified.

## P1 Important

1. Run the Classical Quant-only after-cost locked-OOS evaluation against the
   certified dataset and same-PIT SPY/QQQ benchmarks.
2. Run ablation A/B/C/D with identical dataset, universe, costs, constraints,
   risk, benchmark, and locked-OOS identity; only the LLM feature contribution
   may differ.
3. Calibrate and test the probability overlay on locked-OOS observations and
   either approve or reject the overlay based on real metrics.
4. Evaluate `llm_event_intensity` and any other LLM feature using the promotion
   gate; a valid result may be `SHADOW`, `REJECTED`, or `PRODUCTION_APPROVED`.
5. Establish independent live market-data reconciliation credentials and
   revalidate daily data against a second provider when independent live
   certification is required.

## P2 Optional

1. Add a terminal Research Certification panel that renders the frozen
   Champion/Challenger identity and gate decision from persisted artifacts.
2. Add a text-corpus manifest inspector and import command when a licensed text
   corpus becomes available.
3. Add a Norgate/CRSP-specific vendor conversion script after the licensed
   package is available; the provider-neutral raw landing adapter already
   exists.

## Round 2.5A/B Closure

P0 external-data blockers remain:

1. Provide a licensed Norgate Platinum trial/package or CRSP license that
   permits local derived research.
2. Confirm from the actual package: permanent ID, ticker vintages,
   listing/delisting lifecycle, delisting returns, terminal prices, historical
   membership, PIT corporate actions, PIT total-return vintages, SPY/QQQ PIT
   benchmark.
3. Set `SEC_USER_AGENT` before any real SEC EDGAR acquisition.
4. Provide a CIK-to-`permanent_security_id` mapping manifest sourced from the
   certified market research dataset.

Current status:

- market data: `BLOCKED_EXTERNAL_DATA`
- SEC corpus: `SEC_USER_AGENT_REQUIRED`
- DeepSeek historical replay: `NOT_RUN`
- LLM feature production status: `SHADOW`
