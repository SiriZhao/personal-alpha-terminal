"""ROUND 7: permanent identifier and symbol-history tests."""
from __future__ import annotations

from datetime import date

from personal_alpha_terminal.quant_engine.historical_pit.identifiers import (
    build_instrument_registry,
    resolve_ticker_on,
    symbol_history,
)
from tests.unit.quant_engine.historical_pit.fixtures import build_certified_package


def test_ticker_change_keeps_same_instrument() -> None:
    package = build_certified_package()
    registry = build_instrument_registry(package.securities)
    instruments = {item.instrument_id: item for item in registry.instruments}
    # SEC-B had TB then TBN; both resolve to the same instrument.
    assert "PERM-B" in instruments
    history = symbol_history(registry, "PERM-B")
    tickers = [ticker for ticker, _start, _end in history]
    assert tickers == ["TB", "TBN"]
    assert resolve_ticker_on(registry, "TB", date(2024, 1, 15)) == ("PERM-B",)
    assert resolve_ticker_on(registry, "TBN", date(2024, 3, 15)) == ("PERM-B",)
    assert resolve_ticker_on(registry, "TB", date(2024, 3, 15)) == ()
    assert len(instruments) >= 8


def test_symbol_not_used_as_unique_identity() -> None:
    package = build_certified_package()
    registry = build_instrument_registry(package.securities)
    # Two different tickers of the same company must never map to two ids on a
    # date where only one ticker was valid.
    assert resolve_ticker_on(registry, "TB", date(2024, 1, 15)) == ("PERM-B",)
    assert resolve_ticker_on(registry, "TBN", date(2024, 1, 15)) == ()


def test_identifier_registry_is_deterministic() -> None:
    package = build_certified_package()
    first = build_instrument_registry(package.securities)
    second = build_instrument_registry(package.securities)
    assert first.document() == second.document()
    assert first.blockers == ()
