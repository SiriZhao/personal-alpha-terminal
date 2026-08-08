# Optional LLM Configuration

LLM support is disabled by default and is never required for data, factors, alpha, portfolio construction, risk, decisions, backtests, or diagnostics.

## Supported providers

- OpenAI
- DeepSeek
- Anthropic
- Custom HTTPS OpenAI-compatible endpoint
- Disabled (recommended until explanation output is needed)

Credential environment variables are `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, and `CUSTOM_API_KEY`. Prefer Windows Credential Manager through the project credential helper. Never put keys in source code, Git, logs, screenshots, diagnostic bundles, ordinary backups, or the release directory.

Relevant settings include:

```text
PAT_LLM_PROVIDER=disabled|openai|deepseek|anthropic|custom
PAT_OPENAI_MODEL=<model>
PAT_DEEPSEEK_MODEL=<model>
PAT_ANTHROPIC_MODEL=<model>
PAT_CUSTOM_MODEL=<model>
PAT_CUSTOM_BASE_URL=https://example.com/v1
PAT_LLM_TIMEOUT_SECONDS=60
PAT_LLM_MAX_RETRIES=2
```

Custom and DeepSeek base URLs must use HTTPS. Connection testing verifies configuration/reachability only; it does not generate an investment conclusion.

## Privacy and consent

External AI receives no complete portfolio, account identifier, transaction history, credential, or sensitive configuration by default. Portfolio context requires explicit opt-in and a minimized/redacted payload. Evidence claims are checked against symbol, date, number, unit, direction and source field.

## Hard boundary

AI may explain deterministic results, summarize reports, normalize event text, and assist research. It may not select stocks, calculate factor values, set expected returns/probabilities, choose target weights, size positions, veto risk, or generate/alter BUY and SELL decisions. Timeouts, rate limits, malformed responses, or missing keys degrade only the explanation layer.
