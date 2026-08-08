from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from personal_alpha_terminal.application.decision_service import CandidateView
from personal_alpha_terminal.application.status import SystemReadiness


@dataclass(frozen=True, slots=True)
class DashboardView:
    readiness: SystemReadiness
    market_session: str
    latest_pipeline_date: date | None
    latest_pipeline_status: str
    candidates: tuple[CandidateView, ...]
    tasks: tuple[str, ...]
    generated_at: datetime
    regime_label: str = "Waiting for Data"
    regime_score: Decimal | None = None
    portfolio_name: str | None = None
    portfolio_cash: Decimal | None = None
    portfolio_position_count: int = 0
