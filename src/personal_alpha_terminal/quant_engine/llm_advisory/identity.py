"""ROUND 9: prompt identity and LLM behavior auditability.

Every LLM invocation carries a traceable identity: provider, model, model
version, prompt hash, schema version, temperature and timestamp.  Behavior is
reproducible and attributable; nothing is opaque.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class PromptIdentity:
    provider: str
    model: str
    model_version: str
    prompt_name: str
    prompt_version: str
    prompt_hash: str
    schema_version: str
    temperature: float
    timestamp: datetime

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.provider,
                self.model,
                self.model_version,
                self.prompt_name,
                self.prompt_version,
                self.prompt_hash,
                self.schema_version,
            )
        ):
            raise ValueError("prompt identity is incomplete")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.timestamp.tzinfo is None:
            raise ValueError("prompt identity timestamp must be timezone-aware")

    @property
    def identity_hash(self) -> str:
        return sha256(
            "|".join(
                (
                    self.provider,
                    self.model,
                    self.model_version,
                    self.prompt_name,
                    self.prompt_version,
                    self.prompt_hash,
                    self.schema_version,
                    f"{self.temperature:.6f}",
                )
            ).encode("utf-8")
        ).hexdigest()

    def document(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "model_version": self.model_version,
            "prompt_name": self.prompt_name,
            "prompt_version": self.prompt_version,
            "prompt_hash": self.prompt_hash,
            "schema_version": self.schema_version,
            "temperature": self.temperature,
            "timestamp": self.timestamp.isoformat(),
            "identity_hash": self.identity_hash,
        }


def prompt_hash(prompt_text: str) -> str:
    return sha256(prompt_text.encode("utf-8")).hexdigest()


def build_prompt_identity(
    *,
    provider: str,
    model: str,
    model_version: str,
    prompt_name: str,
    prompt_version: str,
    prompt_text: str,
    schema_version: str,
    temperature: float,
    timestamp: datetime | None = None,
) -> PromptIdentity:
    return PromptIdentity(
        provider=provider,
        model=model,
        model_version=model_version,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        prompt_hash=prompt_hash(prompt_text),
        schema_version=schema_version,
        temperature=temperature,
        timestamp=timestamp or datetime.now(UTC),
    )
