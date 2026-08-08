import math
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from personal_alpha_terminal.data.market_data.contracts import (
    AssetPriceRequest,
    ProviderCapability,
    ProviderRawBar,
)
from personal_alpha_terminal.data.market_data.exceptions import ProviderRequestError

ColumnCandidates = Mapping[str, tuple[str, ...]]


def frame_to_raw_bars(
    frame: Any,
    *,
    request: AssetPriceRequest,
    capability: ProviderCapability,
    columns: ColumnCandidates,
) -> list[ProviderRawBar]:
    """Parse provider fields without normalizing units or creating DB-ready rows."""

    if frame is None or bool(getattr(frame, "empty", False)):
        return []

    normalized_frame = frame.reset_index()
    _flatten_columns(normalized_frame)
    bars: list[ProviderRawBar] = []

    try:
        iterator: Iterable[tuple[object, Any]] = normalized_frame.iterrows()
        for _, row in iterator:
            bar_date = _to_date(_pick(row, columns["date"]))
            if not request.start_date <= bar_date <= request.end_date:
                continue
            bars.append(
                ProviderRawBar(
                    symbol=request.symbol,
                    market=request.market,
                    asset_type=request.asset_type,
                    date=bar_date,
                    open=_to_decimal(_pick(row, columns["open"])),
                    high=_to_decimal(_pick(row, columns["high"])),
                    low=_to_decimal(_pick(row, columns["low"])),
                    close=_to_decimal(_pick(row, columns["close"])),
                    volume=_to_optional_decimal(_pick_optional(row, columns["volume"])),
                    raw_volume_unit=capability.raw_volume_unit,
                    price_currency=request.price_currency,
                    raw_share_unit=capability.raw_share_unit,
                    price_type=capability.price_type,
                    adjusted_close=_to_optional_decimal(
                        _pick_optional(row, columns.get("adjusted_close", ()))
                    ),
                )
            )
    except ProviderRequestError:
        raise
    except Exception as exc:
        raise ProviderRequestError(f"Could not normalize provider response: {exc}") from exc

    return bars


def _flatten_columns(frame: Any) -> None:
    frame_columns = getattr(frame, "columns", ())
    nlevels = getattr(frame_columns, "nlevels", 1)
    if nlevels <= 1:
        return
    frame.columns = [
        str(column[0] if isinstance(column, tuple) else column) for column in frame_columns
    ]


def _pick(row: Any, candidates: tuple[str, ...]) -> Any:
    value = _pick_optional(row, candidates)
    if value is None:
        raise ProviderRequestError(f"Provider response is missing columns: {candidates}")
    return value


def _pick_optional(row: Any, candidates: tuple[str, ...]) -> Any | None:
    for candidate in candidates:
        try:
            if candidate in row:
                value = row[candidate]
                return None if _is_missing(value) else value
        except (KeyError, TypeError):
            continue
    return None


def _to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "to_pydatetime"):
        converted = value.to_pydatetime()
        return converted.date() if isinstance(converted, datetime) else converted
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ProviderRequestError(f"Invalid provider date: {value!r}") from exc


def _to_decimal(value: Any) -> Decimal:
    if _is_missing(value):
        return Decimal("NaN")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("NaN")


def _to_optional_decimal(value: Any | None) -> Decimal | None:
    if _is_missing(value):
        return None
    parsed = _to_decimal(value)
    return parsed if parsed.is_finite() else None


def _is_missing(value: Any | None) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    try:
        result = value != value
        return bool(result) if isinstance(result, bool) else False
    except (TypeError, ValueError):
        return False
