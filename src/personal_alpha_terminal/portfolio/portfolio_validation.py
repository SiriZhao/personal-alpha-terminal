"""Validation for real portfolio ledger entries.

This module is the single source of truth for what a valid user-entered
portfolio looks like.  It never fabricates defaults: a missing or invalid value
is rejected, never replaced with an assumed one.  Short positions are not
supported, so negative share counts are always rejected.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# A ticker must be a short, uppercase-friendly exchange symbol.  We deliberately
# keep the pattern conservative: letters/digits plus '.', '-', '=', '.' variants
# used by US listings.  Empty or whitespace-only tickers are invalid.
_TICKER_PATTERN = re.compile(r"^[A-Za-z^][A-Za-z0-9.\-=^]{0,14}$")


class PortfolioValidationError(ValueError):
    """Raised when a user-entered portfolio field is invalid."""


@dataclass(frozen=True, slots=True)
class ValidatedPosition:
    ticker: str
    shares: Decimal
    average_cost: Decimal | None


def validate_ticker(raw: object) -> str:
    """Return a normalized ticker or raise PortfolioValidationError."""

    text = str(raw).strip() if raw is not None else ""
    if not text:
        raise PortfolioValidationError("ticker must not be empty")
    normalized = text.upper()
    if not _TICKER_PATTERN.match(normalized):
        raise PortfolioValidationError(f"ticker format is invalid: {text!r}")
    return normalized


def _finite_decimal(value: object, label: str) -> Decimal:
    """Convert to a finite Decimal or raise PortfolioValidationError."""

    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, bool):
        raise PortfolioValidationError(f"{label} must be a number, not a boolean")
    elif isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise PortfolioValidationError(f"{label} must be a finite number")
        result = Decimal(str(value))
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("$", "")
        if not cleaned:
            raise PortfolioValidationError(f"{label} must not be empty")
        try:
            result = Decimal(cleaned)
        except InvalidOperation as exc:
            raise PortfolioValidationError(f"{label} is not a valid number: {value!r}") from exc
    else:
        raise PortfolioValidationError(f"{label} must be a number")
    if not result.is_finite():
        raise PortfolioValidationError(f"{label} must be a finite number")
    return result


def validate_cash(raw: object) -> Decimal:
    """Cash must be a finite, non-negative amount."""

    value = _finite_decimal(raw, "cash")
    if value < 0:
        raise PortfolioValidationError("cash must be non-negative")
    return value


def validate_shares(raw: object) -> Decimal:
    """Share counts must be finite and non-negative (no short positions)."""

    value = _finite_decimal(raw, "shares")
    if value < 0:
        raise PortfolioValidationError(
            "shares must be non-negative; short positions are not supported"
        )
    if value == 0:
        raise PortfolioValidationError("shares must be positive to define a position")
    return value


def validate_average_cost(raw: object) -> Decimal:
    """Average cost, when provided, must be finite and positive."""

    value = _finite_decimal(raw, "average cost")
    if value <= 0:
        raise PortfolioValidationError("average cost must be positive")
    return value


def validate_positions(
    rows: list[tuple[object, object, object | None]],
) -> tuple[ValidatedPosition, ...]:
    """Validate a batch of (ticker, shares, average_cost) entries.

    Rejects duplicate tickers, empty tickers, non-finite or negative values.
    Order is preserved in the output.
    """

    seen: set[str] = set()
    validated: list[ValidatedPosition] = []
    for index, (raw_ticker, raw_shares, raw_cost) in enumerate(rows, start=1):
        ticker = validate_ticker(raw_ticker)
        if ticker in seen:
            raise PortfolioValidationError(f"duplicate ticker at entry {index}: {ticker}")
        seen.add(ticker)
        shares = validate_shares(raw_shares)
        average_cost = validate_average_cost(raw_cost) if raw_cost not in (None, "") else None
        validated.append(ValidatedPosition(ticker, shares, average_cost))
    return tuple(validated)
