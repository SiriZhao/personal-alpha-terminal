# DeepSeek Real SEC Replay Validation

Date: 2026-08-12

Result: **real SEC source + real DeepSeek extraction + real replay mechanics**

## 1. Source Requirements

Before extraction, the real SEC raw archive was validated:

- landing zone verification: PASS
- source identity: CIK + accession
- acceptance timestamp: complete
- timezone: complete
- raw checksum: PASS
- normalized checksum: PASS
- PIT source certification: PASS

## 2. DeepSeek Extraction Pilot

Planned before execution:

- documents: 1
- document type: `8-K`
- estimated tokens: 9,412
- conservative estimated cost ceiling: USD 0.20
- configured budget ceiling: 2 requests / 25,000 tokens / USD 0.20

Actual DeepSeek usage recorded by the existing ledger:

- prompt tokens: 11,791
- cached tokens: 11,776
- completion tokens: 237
- estimated cost: USD 0.0001014328
- validation status: `VALID`
- model: `deepseek-v4-flash`

Structured output status: `READY`

The result is a typed `UnifiedEvent` via Pydantic strict JSON validation.

Extraction confidence is data-quality metadata, not a return probability.

## 3. Replay Validation

Four real historical cutoffs were run:

1. before the second 8-K and original 10-K
2. after original 10-K, before amendment
3. before amendment availability
4. after amendment availability

All replay checks passed:

- future filing invisible
- future amendment invisible
- visible filing versions correct
- earlier replay hash unchanged by future filings
- repeated replay deterministic
- real DeepSeek event invisible before its acceptance and visible afterward

Replay artifact:

`artifacts/latest/sec-edgar-real-replay-pilot.json`

## 4. Production Boundary

The replay mechanics are validated on real data, but replay production
readiness remains `NOT_CERTIFIABLE`:

- permanent security mapping is pending
- market data certification is not available for this pilot

No Champion/Challenger, strategy tuning, factor tuning, probability tuning,
LLM feature promotion, production approval, or trading action was performed.

## 5. Real SEC Evidence

- real SEC filings
- real DeepSeek provider request
- real typed extraction event
- real multi-cutoff replay hashes

## 6. Fixture / Test Evidence

- Unit tests use stub providers and synthetic filings.
- Fixture replay tests do not replace the real replay evidence above.

## 7. Final Dependency

`LLM_RESEARCH_DATA_DEPENDENCY = SECURITY_MAPPING_PENDING`
