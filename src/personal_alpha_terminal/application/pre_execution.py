"""ROUND25 PHASE 7: PRE-EXECUTION overnight risk check.

Between the previous completed session close and the next manual execution,
new information may appear (overnight news, gaps, corporate events, halts).
This layer reports it honestly.  It never retrains models, never recomputes
yesterday's alpha, and never cancels an order itself: the worst outcome is
``PRE_EXECUTION_REVIEW_REQUIRED`` -- HUMAN REVIEW REQUIRED.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from personal_alpha_terminal.intelligence.market_news import (
    NewsIntelligenceService,
)

PRE_EXECUTION_CLEAR = "PRE_EXECUTION_CLEAR"
PRE_EXECUTION_REVIEW_REQUIRED = "PRE_EXECUTION_REVIEW_REQUIRED"
PRE_EXECUTION_DATA_UNAVAILABLE = "PRE_EXECUTION_DATA_UNAVAILABLE"
PRE_EXECUTION_DATA_LIMITED = "PRE_EXECUTION_DATA_LIMITED"

CHECK_PASS = "PASS"
CHECK_WARN = "WARN"
CHECK_UNAVAILABLE = "UNAVAILABLE"
CHECK_FAIL = "REVIEW_REQUIRED"


@dataclass(frozen=True, slots=True)
class PreExecutionCheck:
    name: str
    status: str
    detail: str
    evidence: tuple[str, ...] = ()

    def document(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class PreExecutionAssessment:
    status: str
    decision_as_of: datetime
    generated_at: datetime
    checks: tuple[PreExecutionCheck, ...]
    manual_review_required: bool
    llm_authority: str = "NONE"

    def document(self) -> dict[str, object]:
        return {
            "status": self.status,
            "decision_as_of": self.decision_as_of.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "checks": [check.document() for check in self.checks],
            "manual_review_required": self.manual_review_required,
            "llm_authority": self.llm_authority,
            "auto_cancel": False,
            "alpha_recomputation": False,
        }


def check_overnight_news(
    news_service: NewsIntelligenceService,
    *,
    decision_as_of: datetime,
    now: datetime,
    material_symbols: frozenset[str] | None = None,
) -> PreExecutionCheck:
    """Post-decision news touching the formal symbols triggers review."""

    rows = news_service.ledger.load_items()
    post_decision: list[dict[str, Any]] = []
    for row in rows:
        available_raw = row.get("available_at")
        if not isinstance(available_raw, str):
            continue
        try:
            available_at = datetime.fromisoformat(available_raw)
        except ValueError:
            continue
        if available_at.tzinfo is None:
            available_at = available_at.replace(tzinfo=UTC)
        if decision_as_of < available_at <= now:
            post_decision.append(row)
    if not post_decision:
        return PreExecutionCheck(
            "overnight_news",
            CHECK_PASS,
            "no post-decision news rows between decision cutoff and now",
        )
    material = post_decision
    if material_symbols:

        def touches(row: dict[str, Any]) -> bool:
            symbols = row.get("symbols") or []
            return any(str(symbol) in material_symbols for symbol in symbols)

        material = [row for row in post_decision if touches(row)]
    if material:
        headlines = [str(row.get("headline", "")) for row in material[:5]]
        return PreExecutionCheck(
            "overnight_news",
            CHECK_FAIL,
            (
                f"{len(material)} post-decision news row(s) may be material; "
                "human review required before executing yesterday's plan"
            ),
            tuple(headlines),
        )
    return PreExecutionCheck(
        "overnight_news",
        CHECK_WARN,
        (
            f"{len(post_decision)} post-decision news row(s) exist but none "
            "touch the formal symbols; shown for context"
        ),
        tuple(str(row.get("headline", "")) for row in post_decision[:5]),
    )


def check_market_gap(
    *,
    decision_close: float | None,
    latest_close: float | None,
    threshold: float = 0.03,
) -> PreExecutionCheck:
    """Severe gap detection when both closes are reliably available."""

    if decision_close is None or latest_close is None:
        return PreExecutionCheck(
            "market_gap",
            CHECK_UNAVAILABLE,
            "overnight gap evidence unavailable; cannot fabricate safety",
        )
    if decision_close <= 0 or latest_close <= 0:
        return PreExecutionCheck(
            "market_gap",
            CHECK_UNAVAILABLE,
            "non-positive close; gap evidence unusable",
        )
    gap = latest_close / decision_close - 1.0
    if abs(gap) >= threshold:
        return PreExecutionCheck(
            "market_gap",
            CHECK_FAIL,
            f"severe market gap {gap:+.2%} between decision close and latest close",
            (f"gap={gap:.6f}",),
        )
    return PreExecutionCheck(
        "market_gap",
        CHECK_PASS,
        f"gap {gap:+.2%} below {threshold:.0%} review threshold",
        (f"gap={gap:.6f}",),
    )


def check_stale_market_data(
    *, latest_available_at: datetime | None, decision_as_of: datetime, now: datetime
) -> PreExecutionCheck:
    if latest_available_at is None:
        return PreExecutionCheck(
            "market_data_freshness",
            CHECK_UNAVAILABLE,
            "no verified latest-price timestamp; PRE_EXECUTION_DATA_LIMITED",
        )
    if latest_available_at.tzinfo is None:
        latest_available_at = latest_available_at.replace(tzinfo=UTC)
    if latest_available_at < decision_as_of:
        return PreExecutionCheck(
            "market_data_freshness",
            CHECK_FAIL,
            (
                "market data is older than the decision cutoff; "
                "stale-price risk requires human review"
            ),
            (latest_available_at.isoformat(),),
        )
    return PreExecutionCheck(
        "market_data_freshness",
        CHECK_PASS,
        f"latest verified price available at {latest_available_at.isoformat()}",
    )


def check_halts_and_corporate_events(
    *,
    halted_symbols: frozenset[str] | None = None,
    material_events: tuple[str, ...] = (),
    event_rows: tuple[dict[str, Any], ...] = (),
) -> PreExecutionCheck:
    if halted_symbols:
        return PreExecutionCheck(
            "halts_and_events",
            CHECK_FAIL,
            f"halted/delisted symbols detected: {sorted(halted_symbols)}",
            tuple(sorted(halted_symbols)),
        )
    material = [row for row in event_rows if row.get("is_material")]
    details = list(material_events)
    if material:
        details.extend(str(row.get("summary", row.get("event_type", ""))) for row in material[:5])
    if details:
        return PreExecutionCheck(
            "halts_and_events",
            CHECK_FAIL,
            "new material corporate/SEC event(s) after decision; human review required",
            tuple(details),
        )
    if event_rows:
        return PreExecutionCheck(
            "halts_and_events",
            CHECK_WARN,
            f"{len(event_rows)} post-decision event row(s), none material",
        )
    return PreExecutionCheck(
        "halts_and_events",
        CHECK_PASS,
        "no halt/delisting and no material post-decision event",
    )


def build_assessment(
    *,
    decision_as_of: datetime,
    now: datetime | None = None,
    checks: tuple[PreExecutionCheck, ...],
) -> PreExecutionAssessment:
    runtime = (now or datetime.now(UTC)).astimezone(UTC)
    decision = decision_as_of.astimezone(UTC)
    statuses = [check.status for check in checks]
    if CHECK_UNAVAILABLE in statuses and CHECK_FAIL not in statuses:
        status = PRE_EXECUTION_DATA_LIMITED
        review = True
    elif CHECK_FAIL in statuses:
        status = PRE_EXECUTION_REVIEW_REQUIRED
        review = True
    elif CHECK_WARN in statuses:
        status = PRE_EXECUTION_CLEAR
        review = False
    else:
        status = PRE_EXECUTION_CLEAR
        review = False
    return PreExecutionAssessment(
        status=status,
        decision_as_of=decision,
        generated_at=runtime,
        checks=checks,
        manual_review_required=review,
    )


def post_decision_news_count(
    news_service: NewsIntelligenceService,
    *,
    decision_as_of: datetime,
    now: datetime,
) -> int:
    count = 0
    for row in news_service.ledger.load_items():
        available_raw = row.get("available_at")
        if not isinstance(available_raw, str):
            continue
        try:
            available_at = datetime.fromisoformat(available_raw)
        except ValueError:
            continue
        if available_at.tzinfo is None:
            available_at = available_at.replace(tzinfo=UTC)
        if decision_as_of < available_at <= now:
            count += 1
    return count
