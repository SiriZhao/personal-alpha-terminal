from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.models import ProviderCapabilityRecord


@dataclass(frozen=True, slots=True)
class ProviderCapabilityEvidence:
    provider: str
    market: str
    asset_type: str
    fields: tuple[str, ...]
    earliest_date: date | None
    latest_date: date | None
    adjustment_semantics: str
    availability_status: str
    verified_at: datetime | None

    def supports(self, field: str, *, on_date: date) -> bool:
        return bool(
            self.availability_status == "AVAILABLE"
            and field in self.fields
            and (self.earliest_date is None or self.earliest_date <= on_date)
            and (self.latest_date is None or on_date <= self.latest_date)
        )


class ProviderCapabilityRegistry:
    """Persisted provider claims; no provider is promoted by successful download alone."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def evidence(
        self,
        *,
        provider: str,
        market: str,
        asset_type: str,
    ) -> ProviderCapabilityEvidence | None:
        record = self.session.scalar(
            select(ProviderCapabilityRecord).where(
                ProviderCapabilityRecord.provider == provider,
                ProviderCapabilityRecord.market == market,
                ProviderCapabilityRecord.asset_type == asset_type,
            )
        )
        if record is None:
            return None
        return ProviderCapabilityEvidence(
            provider=record.provider,
            market=record.market,
            asset_type=record.asset_type,
            fields=tuple(record.fields),
            earliest_date=record.earliest_date,
            latest_date=record.latest_date,
            adjustment_semantics=record.adjustment_semantics,
            availability_status=record.availability_status,
            verified_at=record.verified_at,
        )
