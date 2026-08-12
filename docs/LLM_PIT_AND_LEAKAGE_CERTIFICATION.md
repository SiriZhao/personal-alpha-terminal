# LLM PIT and Leakage Certification

Classification: `NOT_CERTIFIABLE` for historical production research.

Implemented invariants:

- each document distinguishes publication, filing, acceptance, provider receipt,
  availability, processing and decision cutoff;
- a document is visible only when `available_at <= decision_as_of`;
- backtest-safe events reject evidence whose availability exceeds the cutoff;
- historical replay re-filters both documents and event evidence at every cutoff;
- changing a future document cannot alter an earlier replay hash;
- feature time precedes condition time, which strictly precedes outcome time;
- external document instructions are untrusted content and cannot control prompts;
- cached output is isolated by source checksum, model and prompt version.

Automated tests cover future-document exclusion, outcome leakage, malformed JSON,
mock-output rejection and prompt-injection boundaries. These software controls pass,
but the project has no certified historical text/news/transcript corpus and its
market research dataset remains `NOT_CERTIFIABLE`. Therefore historical AI replay
can be executed on controlled test fixtures only; fixture results are not investment
or promotion evidence.
