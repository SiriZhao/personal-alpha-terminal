# ROUND43 Point-in-Time Event Ledger

- Date: 2026-08-17
- Engineering status: PASS
- Round acceptance: PASS

Implemented append-oriented `EventLedger`, content-hash deduplication,
immutable revision chains, explicit `available_at`, reproducible
`EventSnapshot`, cutoff replay, and future/outcome contamination checks.
Historical LLM replay is excluded from promotion evidence.
Its explicit status is `ENGINEERING_ONLY`, never production promotion
evidence.

No event later than the decision cutoff is made visible by replay.
