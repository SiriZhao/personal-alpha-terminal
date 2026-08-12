"""Shared provider normalization helpers (ROUND 10).

``frame_to_raw_bars`` now delegates to the canonical normalization module so
every provider (Yahoo, Stooq, AKShare) shares one robust schema handler that
supports MultiIndex columns, single/batch tickers and strict Close validation.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from personal_alpha_terminal.data.market_data.contracts import (
    AssetPriceRequest,
    ProviderCapability,
    ProviderRawBar,
)
from personal_alpha_terminal.data.market_data.providers.canonical import (
    normalize_provider_frame,
)

ColumnCandidates = Mapping[str, tuple[str, ...]]


def frame_to_raw_bars(
    frame: Any,
    *,
    request: AssetPriceRequest,
    capability: ProviderCapability,
    columns: ColumnCandidates,
) -> list[ProviderRawBar]:
    """Parse provider fields without normalizing units or creating DB-ready rows.

    Robustly handles single-level and MultiIndex columns (both price/ticker
    orderings) and never silently stores a NaN Close.
    """
    return normalize_provider_frame(
        frame,
        request=request,
        capability=capability,
        columns=columns,
    )
