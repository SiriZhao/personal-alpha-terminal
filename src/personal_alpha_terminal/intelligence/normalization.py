from __future__ import annotations

import re

from personal_alpha_terminal.intelligence.schemas import EventType

_EVENT_ALIASES: dict[str, EventType] = {
    "M&A": EventType.MERGER_ACQUISITION,
    "MERGER": EventType.MERGER_ACQUISITION,
    "ACQUISITION": EventType.MERGER_ACQUISITION,
    "EPS": EventType.EARNINGS,
    "EARNINGS_RELEASE": EventType.EARNINGS,
    "REVENUE_SURPRISE": EventType.REVENUE,
    "GUIDANCE_CHANGE": EventType.GUIDANCE,
    "FEDERAL_RESERVE": EventType.FED,
    "RATE": EventType.YIELD,
    "RATES": EventType.YIELD,
    "USD": EventType.DOLLAR,
    "CRUDE_OIL": EventType.OIL,
}


def normalize_event_type(value: str) -> EventType:
    normalized = re.sub(r"[^A-Z0-9]+", "_", value.strip().upper()).strip("_")
    if normalized in _EVENT_ALIASES:
        return _EVENT_ALIASES[normalized]
    try:
        return EventType(normalized)
    except ValueError:
        return EventType.OTHER


def normalize_symbol(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[^A-Z0-9.\-]", "", value.strip().upper())
    return normalized or None


def normalize_tags(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(sorted({item.strip().lower() for item in values if item.strip()}))
