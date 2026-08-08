from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class ProgramStatus(StrEnum):
    STARTING = "STARTING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"


class DataStatus(StrEnum):
    EMPTY = "EMPTY"
    INITIALIZING = "INITIALIZING"
    SYNCING = "SYNCING"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    CERTIFIED = "CERTIFIED"
    PROVIDER_ERROR = "PROVIDER_ERROR"


class ModelStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    RUNNING = "RUNNING"
    READY = "READY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class StatusDetail:
    code: str
    title_zh: str
    summary: str
    technical_reason: str
    repair_action: str
    allow_research: bool
    allow_candidates: bool
    updated_at: datetime

    @classmethod
    def build(
        cls,
        code: StrEnum,
        title_zh: str,
        summary: str,
        technical_reason: str,
        repair_action: str,
        *,
        allow_research: bool = False,
        allow_candidates: bool = False,
        updated_at: datetime | None = None,
    ) -> StatusDetail:
        return cls(
            code=code.value,
            title_zh=title_zh,
            summary=summary,
            technical_reason=technical_reason,
            repair_action=repair_action,
            allow_research=allow_research,
            allow_candidates=allow_candidates,
            updated_at=updated_at or datetime.now(UTC),
        )


@dataclass(frozen=True, slots=True)
class SystemReadiness:
    program: StatusDetail
    database: StatusDetail
    data: StatusDetail
    model: StatusDetail
