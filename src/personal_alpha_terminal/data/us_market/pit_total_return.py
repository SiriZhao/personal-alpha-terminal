from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from math import isfinite


@dataclass(frozen=True, slots=True)
class PITRawBar:
    permanent_security_id: str
    trade_date: date
    close: float
    source_id: str
    available_at: datetime

    def __post_init__(self) -> None:
        if not self.permanent_security_id.strip() or not self.source_id.strip():
            raise ValueError("raw bar requires permanent id and source lineage")
        if not isfinite(self.close) or self.close <= 0:
            raise ValueError("raw close must be finite and positive")
        if self.available_at.tzinfo is None:
            raise ValueError("raw bar available_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class PITCorporateAction:
    action_id: str
    revision_id: str
    permanent_security_id: str
    action_type: str
    effective_date: date
    announcement_at: datetime | None
    available_at: datetime
    source_id: str
    split_ratio: float | None = None
    cash_amount: float | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        if self.available_at.tzinfo is None:
            raise ValueError("corporate-action timestamps must be timezone-aware")
        if self.announcement_at is not None and self.announcement_at.tzinfo is None:
            raise ValueError("corporate-action announcement timestamp must be timezone-aware")
        if self.announcement_at is not None and self.announcement_at > self.available_at:
            raise ValueError("corporate action cannot be available before announcement")
        if not all(
            item.strip()
            for item in (
                self.action_id,
                self.revision_id,
                self.permanent_security_id,
                self.action_type,
                self.source_id,
            )
        ):
            raise ValueError("corporate action requires immutable identifiers and lineage")
        if self.action_type in {"split", "reverse_split", "stock_dividend"}:
            if self.split_ratio is None or not isfinite(self.split_ratio) or self.split_ratio <= 0:
                raise ValueError("share-changing action requires a positive split_ratio")
        if self.action_type == "cash_dividend":
            if self.cash_amount is None or not isfinite(self.cash_amount) or self.cash_amount < 0:
                raise ValueError("cash dividend requires a nonnegative cash amount")
            if self.currency != "USD":
                raise ValueError("US cash dividends require explicit USD currency")


@dataclass(frozen=True, slots=True)
class PITTotalReturnPoint:
    trade_date: date
    raw_close: float
    period_return: float
    total_return_index: float
    applied_action_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PITTotalReturnSeries:
    permanent_security_id: str
    as_of_time: datetime
    version_id: str
    source_ids: tuple[str, ...]
    points: tuple[PITTotalReturnPoint, ...]
    adjustment_method: str = "point_in_time_total_return"


class PointInTimeTotalReturnBuilder:
    """Build a reproducible total-return index from raw closes and vintage actions.

    The builder never accepts provider-adjusted closes.  Non-cash merger, spin-off,
    rights, ADR-ratio and delisting consideration require explicit valuation logic and
    therefore fail closed instead of guessing a return.
    """

    _NON_PRICE_ACTIONS = {"symbol_change"}
    _UNSUPPORTED_VALUE_ACTIONS = {
        "merger_consideration",
        "spin_off",
        "rights",
        "delisting_payment",
        "adr_ratio_change",
    }

    def build(
        self,
        *,
        bars: tuple[PITRawBar, ...],
        actions: tuple[PITCorporateAction, ...],
        as_of_time: datetime,
    ) -> PITTotalReturnSeries:
        if as_of_time.tzinfo is None:
            raise ValueError("as_of_time must be timezone-aware")
        if len(bars) < 2:
            raise ValueError("at least two raw bars are required")
        ordered = tuple(sorted(bars, key=lambda item: item.trade_date))
        ids = {item.permanent_security_id for item in ordered}
        if len(ids) != 1:
            raise ValueError("a PIT total-return build cannot mix securities")
        dates = [item.trade_date for item in ordered]
        if len(dates) != len(set(dates)):
            raise ValueError("raw bars contain duplicate trade dates")
        cutoff = as_of_time.astimezone(UTC)
        if any(item.available_at.astimezone(UTC) > cutoff for item in ordered):
            raise ValueError("raw bar was unavailable at the requested PIT cutoff")
        if any(item.trade_date > cutoff.date() for item in ordered):
            raise ValueError("raw bar is dated after the requested PIT cutoff")

        security_id = ordered[0].permanent_security_id
        relevant: list[PITCorporateAction] = []
        revision_keys: set[tuple[str, str]] = set()
        for action in actions:
            if action.permanent_security_id != security_id:
                raise ValueError("corporate-action ledger mixes securities")
            key = (action.action_id, action.revision_id)
            if key in revision_keys:
                raise ValueError("duplicate corporate-action revision")
            revision_keys.add(key)
            if action.available_at.astimezone(UTC) <= cutoff:
                relevant.append(action)
        effective: dict[date, list[PITCorporateAction]] = {}
        for action in relevant:
            if action.effective_date <= cutoff.date():
                effective.setdefault(action.effective_date, []).append(action)

        level = 1.0
        points = [PITTotalReturnPoint(ordered[0].trade_date, ordered[0].close, 0.0, level, ())]
        previous = ordered[0]
        for current in ordered[1:]:
            day_actions = tuple(
                sorted(effective.get(current.trade_date, []), key=lambda a: a.action_id)
            )
            unsupported = [
                action.action_type
                for action in day_actions
                if action.action_type in self._UNSUPPORTED_VALUE_ACTIONS
            ]
            if unsupported:
                raise ValueError(
                    "explicit valuation is required for corporate actions: "
                    + ", ".join(sorted(set(unsupported)))
                )
            split_ratio = 1.0
            cash = 0.0
            applied: list[str] = []
            for action in day_actions:
                if action.action_type in {"split", "reverse_split", "stock_dividend"}:
                    ratio = action.split_ratio
                    if ratio is None:
                        raise ValueError("share-changing action is missing split_ratio")
                    split_ratio *= ratio
                    applied.append(action.action_id)
                elif action.action_type == "cash_dividend":
                    amount = action.cash_amount
                    if amount is None:
                        raise ValueError("cash dividend is missing cash_amount")
                    cash += amount
                    applied.append(action.action_id)
                elif action.action_type in self._NON_PRICE_ACTIONS:
                    applied.append(action.action_id)
                else:
                    raise ValueError(f"unsupported corporate action type: {action.action_type}")
            gross = (current.close * split_ratio + cash) / previous.close
            period_return = gross - 1.0
            if not isfinite(period_return) or period_return <= -1:
                raise ValueError("corporate-action-adjusted return is invalid")
            level *= gross
            points.append(
                PITTotalReturnPoint(
                    current.trade_date,
                    current.close,
                    period_return,
                    level,
                    tuple(applied),
                )
            )
            previous = current

        source_ids = tuple(
            sorted({item.source_id for item in ordered} | {item.source_id for item in relevant})
        )
        payload = {
            "security": security_id,
            "as_of": cutoff.isoformat(),
            "bars": [asdict(item) for item in ordered],
            "actions": [asdict(item) for item in relevant],
            "points": [asdict(item) for item in points],
        }
        version_id = sha256(
            json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return PITTotalReturnSeries(
            permanent_security_id=security_id,
            as_of_time=cutoff,
            version_id=version_id,
            source_ids=source_ids,
            points=tuple(points),
        )
