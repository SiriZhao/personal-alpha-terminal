# LLM Cost and Reliability Report

Real DeepSeek smoke, 2026-08-12:

| Field | Result |
|---|---:|
| Provider | DeepSeek |
| Model | `deepseek-v4-flash` |
| HTTP / structured validation | success / `VALID` |
| Prompt tokens | 43 |
| Completion tokens | 5 |
| Gateway latency | 10,708 ms |
| Estimated cost | USD 0.00000742 |
| Usage ledger records | 1 |
| Request/response hashes | present |

The request used the inherited `DEEPSEEK_API_KEY`; no credential value was printed,
persisted or committed. The gateway categorizes authentication, rate limit, quota,
timeout, provider and schema failures without serializing headers. Existing content
hash caching prevents repeat extraction for the same document/model/prompt identity.

This single request proves connectivity and parsing, not availability SLA or model
quality. Monthly cost is intentionally not projected from one request. Daily usage
must be measured from immutable usage records after a real certified document feed
exists.

A second real call completed the full `RawInformation -> DeepSeek -> typed event`
path on an isolated `TEST_FIXTURE`. It produced a schema-valid `EARNINGS` event and
was not persisted or counted as market, factor, OOS or promotion evidence. Automated
failure tests cover timeout, rate limiting, provider outage, malformed JSON and
disabled-provider fallback without exposing credential values.
