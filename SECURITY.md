# Security Policy

## Supported behavior

Personal Alpha Terminal is a local manual-decision quantitative terminal.
It must never:

- auto-submit orders;
- connect to a broker API;
- store API keys in source;
- expose SEC_EDGAR_USER_AGENT or DeepSeek credentials;
- let LLM output control Alpha, probability, targets, or recommendations.

## Credential handling

Store credentials only in user or process environment variables:

- DEEPSEEK_API_KEY
- PAT_LLM_PROVIDER
- SEC_EDGAR_USER_AGENT

Do not write keys into config.yaml, .env, source, docs, reports, or commit
history.

## Fail-closed rules

- Data, PIT, future-leakage, signal, portfolio, risk, and execution gates are
  mandatory.
- If validation evidence is missing, the system returns NO_ACTION / BLOCKED.
- OperationalPolicy can never bypass data, PIT, signal, portfolio, risk, or
  execution gates.
- LLM production influence must remain NONE until explicit user-approved
  promotion evidence exists.

## Reporting a vulnerability

This is a personal project. If you find a security issue, do not post secrets.
Contact the repository owner privately with a minimal reproduction and avoid
including live credentials or personal holdings.

## Secret scan

Before any push or release, run:

```powershell
.\.venv314\Scripts\python.exe scripts\secret_scan.py
```

The expected result is `SECRET_SCAN_PASS`.