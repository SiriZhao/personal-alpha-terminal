# AI-Native Quant Architecture

Status date: 2026-08-12

The production boundary is:

`certified PIT data -> PIT text/event intelligence -> typed LLM features -> deterministic factors -> statistical probability -> portfolio -> risk -> manual proposal`

DeepSeek is accessed only through the provider-neutral `LLMProvider` and audited
`LLMGateway`. `LLMRouter`, `PromptRegistry`, `ModelRegistry`, immutable extraction
cache and `LLMUsageLedger` separate model selection, prompt identity, execution and
provenance. Quant-facing output must be a JSON object and then pass a typed Pydantic
schema. A malformed response is rejected; free text is never parsed as a factor.

The current substantive vertical slice is Event Intelligence. A raw document keeps
published, filed, accepted, provider-received, available, processed and cutoff time
boundaries. DeepSeek extracts a typed event taxonomy and earnings/filing attributes,
including tone and risk deltas. A cross-sectional engine converts only PIT-visible,
backtest-safe events into a winsorized, sector-demeaned SHADOW factor. Extraction
confidence remains data-quality metadata and is never a statistical return
probability.

Production decisions remain deterministic. LLM features have zero production
weight until exact-version market data, text data, factor, probability calibration,
walk-forward, locked OOS, costs and ablation evidence pass the promotion gate. An
LLM/API/schema/budget failure selects the classical Champion; it does not create a
substitute value or block valid classical analysis.

Feature flags default to Event Intelligence only. Filing Intelligence, relationship
promotion, embeddings and the research agent remain off until their data and
validation requirements are met. Existing relationship/narrative research code is
not a production signal.
