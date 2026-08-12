# LLM Factor Registry

| Factor | Source | PIT rule | Normalization | Probability role | Status |
|---|---|---|---|---|---|
| `llm_event_intensity` | typed DeepSeek event extraction | `document.available_at <= decision_as_of` | daily winsorization, sector demeaning, cross-sectional z-score | none until separately calibrated | `SHADOW` |

The factor is bound to `event-extraction-v2` and the configured model version. Its
raw value uses event direction, relevance, novelty and bounded magnitude. LLM
extraction confidence is stored separately. Missing certified text is unavailable;
it is not silently replaced by a bullish, bearish or probability value.

No LLM factor is `PRODUCTION_APPROVED`. Filing delta fields are present in the typed
event schema, but the dedicated filing feed is disabled because no certified
historical filing/transcript package is available. Relationship, narrative and
semantic factors remain research-only or unimplemented rather than placeholders
that affect portfolio decisions.
