"""Provider-level circuit breaker for ROUND 10.

A provider that trips a structural incident (BOT_CHALLENGE, SCHEMA_CHANGED,
HTTP_BLOCKED, AUTH_REQUIRED, RATE_LIMITED) is opened so the bulk sync stops
repeating requests for thousands of tickers.  The circuit is not permanent:
the next run may probe health and recover.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from personal_alpha_terminal.data.market_data.error_classification import (
    ProviderErrorClassification,
    circuit_tripping,
)


class ProviderCircuitState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    OPEN_CIRCUIT = "OPEN_CIRCUIT"
    RECOVERING = "RECOVERING"


@dataclass(frozen=True, slots=True)
class ProviderCircuitRecord:
    provider: str
    state: ProviderCircuitState
    reason: str | None
    opened_at: datetime | None
    failure_count: int
    sample_symbols: tuple[str, ...]
    last_success_at: datetime | None
    consecutive_tripping: int

    def document(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "state": self.state.value,
            "reason": self.reason,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "failure_count": self.failure_count,
            "sample_symbols": list(self.sample_symbols),
            "last_success_at": (
                self.last_success_at.isoformat() if self.last_success_at else None
            ),
            "consecutive_tripping": self.consecutive_tripping,
        }


class ProviderCircuitBreaker:
    """Fail-closed provider gating with a recoverable open state."""

    def __init__(
        self,
        root: Path,
        *,
        trip_threshold: int = 5,
        failure_rate_threshold: float = 0.5,
        window_size: int = 50,
        probe_interval_seconds: float = 300.0,
    ) -> None:
        self.root = root
        self.trip_threshold = trip_threshold
        self.failure_rate_threshold = failure_rate_threshold
        self.window_size = window_size
        self.min_observations = 10
        self.probe_interval_seconds = probe_interval_seconds
        self._records: dict[str, ProviderCircuitRecord] = {}
        self._outcomes: dict[str, list[bool]] = {}
        self._load()

    def state(self, provider: str) -> ProviderCircuitState:
        record = self._records.get(provider)
        if record is None:
            return ProviderCircuitState.HEALTHY
        return record.state

    def allows_request(self, provider: str, *, now: datetime | None = None) -> bool:
        """OPEN_CIRCUIT blocks requests; RECOVERING allows a single health probe."""
        state = self.state(provider)
        if state is ProviderCircuitState.OPEN_CIRCUIT:
            return False
        if state is ProviderCircuitState.RECOVERING:
            return self._probe_due(provider, now)
        return True

    def record_success(self, provider: str, *, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        self._push_outcome(provider, True)
        failure_rate = self._failure_rate(provider)
        record = self._records.get(provider)
        if record is not None and record.state is ProviderCircuitState.RECOVERING:
            self._records[provider] = ProviderCircuitRecord(
                provider=provider,
                state=ProviderCircuitState.HEALTHY,
                reason=None,
                opened_at=None,
                failure_count=0,
                sample_symbols=(),
                last_success_at=current,
                consecutive_tripping=0,
            )
        else:
            self._records[provider] = ProviderCircuitRecord(
                provider=provider,
                state=(
                    ProviderCircuitState.DEGRADED
                    if failure_rate >= self.failure_rate_threshold
                    else ProviderCircuitState.HEALTHY
                ),
                reason=(
                    "recovering failure rate"
                    if failure_rate >= self.failure_rate_threshold
                    else None
                ),                opened_at=None,
                failure_count=0,
                sample_symbols=(),
                last_success_at=current,
                consecutive_tripping=0,
            )
        self._save()

    def record_failure(
        self,
        provider: str,
        classification: ProviderErrorClassification,
        *,
        symbol: str,
        now: datetime | None = None,
    ) -> ProviderCircuitState:
        current = now or datetime.now(UTC)
        self._push_outcome(provider, False)
        record = self._records.get(provider)
        previous_failures = record.failure_count if record else 0
        previous_consecutive = record.consecutive_tripping if record else 0
        samples = tuple(dict.fromkeys((*(record.sample_symbols if record else ()), symbol)))[:10]
        consecutive = previous_consecutive + 1 if circuit_tripping(classification) else 0
        failure_count = previous_failures + 1
        failure_rate = self._failure_rate(provider)
        outcome_count = len(self._outcomes.get(provider, []))
        reason = None
        state = ProviderCircuitState.DEGRADED
        if consecutive >= self.trip_threshold or (
            outcome_count >= self.min_observations
            and failure_rate >= self.failure_rate_threshold
        ):
            state = ProviderCircuitState.OPEN_CIRCUIT
            reason = (
                f"tripped after {failure_count} failures "
                f"(consecutive {classification.value}={consecutive}, "
                f"failure_rate={failure_rate:.2f})"
            )
        self._records[provider] = ProviderCircuitRecord(
            provider=provider,
            state=state,
            reason=reason,
            opened_at=(current if state is ProviderCircuitState.OPEN_CIRCUIT else None),
            failure_count=failure_count,
            sample_symbols=samples,
            last_success_at=(record.last_success_at if record else None),
            consecutive_tripping=consecutive,
        )
        self._save()
        return state

    def mark_recovering(self, provider: str, *, now: datetime | None = None) -> None:
        record = self._records.get(provider)
        self._records[provider] = ProviderCircuitRecord(
            provider=provider,
            state=ProviderCircuitState.RECOVERING,
            reason="scheduled health probe",
            opened_at=(record.opened_at if record else None),
            failure_count=(record.failure_count if record else 0),
            sample_symbols=(record.sample_symbols if record else ()),
            last_success_at=(record.last_success_at if record else None),
            consecutive_tripping=0,
        )
        self._save()

    def report(self) -> tuple[ProviderCircuitRecord, ...]:
        return tuple(self._records[provider] for provider in sorted(self._records))

    # ------------------------------------------------------------------

    def _probe_due(self, provider: str, now: datetime | None) -> bool:
        record = self._records.get(provider)
        if record is None or record.opened_at is None:
            return True
        current = now or datetime.now(UTC)
        return (current - record.opened_at).total_seconds() >= self.probe_interval_seconds

    def _push_outcome(self, provider: str, ok: bool) -> None:
        outcomes = self._outcomes.setdefault(provider, [])
        outcomes.append(ok)
        if len(outcomes) > self.window_size:
            del outcomes[: len(outcomes) - self.window_size]

    def _failure_rate(self, provider: str) -> float:
        outcomes = self._outcomes.get(provider, [])
        if not outcomes:
            return 0.0
        return sum(1 for item in outcomes if not item) / len(outcomes)

    def _load(self) -> None:
        path = self._path()
        if not path.exists():
            return
        try:
            payload = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
        except (OSError, TypeError, ValueError):
            return
        for provider, document in payload.items():
            try:
                self._records[str(provider)] = _record_from_document(
                    str(provider), cast(dict[str, Any], document)
                )
            except (KeyError, TypeError, ValueError):
                continue

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            provider: record.document() for provider, record in self._records.items()
        }
        path = self._path()
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _path(self) -> Path:
        return self.root / "provider-circuit-breaker.json"


def _record_from_document(provider: str, document: dict[str, Any]) -> ProviderCircuitRecord:
    return ProviderCircuitRecord(
        provider=provider,
        state=ProviderCircuitState(str(document["state"])),
        reason=(str(document["reason"]) if document.get("reason") else None),
        opened_at=(
            datetime.fromisoformat(str(document["opened_at"]))
            if document.get("opened_at")
            else None
        ),
        failure_count=int(document["failure_count"]),
        sample_symbols=tuple(str(item) for item in cast(list[Any], document["sample_symbols"])),
        last_success_at=(
            datetime.fromisoformat(str(document["last_success_at"]))
            if document.get("last_success_at")
            else None
        ),
        consecutive_tripping=int(document["consecutive_tripping"]),
    )
