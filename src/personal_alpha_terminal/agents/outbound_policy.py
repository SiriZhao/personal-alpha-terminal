from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

SENSITIVE_FIELDS = {
    "account_id",
    "account_number",
    "portfolio_value",
    "cash_balance",
    "quantity",
    "actual_shares",
    "transaction_history",
    "api_key",
    "authorization",
    "token",
}


@dataclass(frozen=True, slots=True)
class AIOutboundAudit:
    provider: str
    model: str
    prompt_version: str
    prompt_hash: str
    input_evidence_hash: str
    output_hash: str
    timestamp: datetime


def redact_outbound_payload(
    payload: dict[str, object], *, portfolio_context_opt_in: bool = False
) -> dict[str, object]:
    def redact(value: object) -> object:
        if isinstance(value, dict):
            return {
                str(key): redact(item)
                for key, item in value.items()
                if portfolio_context_opt_in or str(key).lower() not in SENSITIVE_FIELDS
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    result = redact(payload)
    assert isinstance(result, dict)
    return result


def verify_numeric_claim(
    *,
    claim: dict[str, object],
    evidence: dict[str, object],
) -> bool:
    """Validate that a structured claim is supported by the cited evidence fields."""

    required = {"symbol", "date", "field", "value", "unit", "direction"}
    if required - set(claim):
        return False
    if claim["symbol"] != evidence.get("symbol") or claim["date"] != evidence.get("date"):
        return False
    field = str(claim["field"])
    value = evidence.get(field)
    if not isinstance(value, (int, float)) or not isinstance(claim["value"], (int, float)):
        return False
    if abs(float(value) - float(claim["value"])) > max(1e-9, abs(float(value)) * 1e-9):
        return False
    if claim["unit"] != evidence.get(f"{field}_unit"):
        return False
    direction = "positive" if float(value) > 0 else "negative" if float(value) < 0 else "flat"
    return claim["direction"] == direction and bool(evidence.get("source_field", field))


def build_ai_audit(
    *,
    provider: str,
    model: str,
    prompt_version: str,
    prompt: str,
    evidence_payload: dict[str, object],
    output: str,
    now: datetime | None = None,
) -> AIOutboundAudit:
    canonical = json.dumps(evidence_payload, sort_keys=True, default=str, separators=(",", ":"))
    return AIOutboundAudit(
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        prompt_hash=sha256(prompt.encode()).hexdigest(),
        input_evidence_hash=sha256(canonical.encode()).hexdigest(),
        output_hash=sha256(output.encode()).hexdigest(),
        timestamp=now or datetime.now(UTC),
    )
