"""Validation contract tests for the real portfolio ledger.

These tests lock down the user-input rules for portfolio-init /
portfolio-import: no negative values, no NaN/Inf, no duplicate or empty
tickers, and no implicit cash.  They never touch the production database.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from personal_alpha_terminal.portfolio.portfolio_validation import (
    PortfolioValidationError,
    ValidatedPosition,
    validate_average_cost,
    validate_cash,
    validate_positions,
    validate_shares,
    validate_ticker,
)


def test_valid_ticker_is_normalized_to_uppercase() -> None:
    assert validate_ticker("  aapl ") == "AAPL"
    assert validate_ticker("BRK.B") == "BRK.B"
    assert validate_ticker("^VIX") == "^VIX"


@pytest.mark.parametrize("raw", ["", "   ", None, "1", "-AAPL", "WAYTOOLONGTICKERX"])
def test_invalid_ticker_is_rejected(raw: object) -> None:
    with pytest.raises(PortfolioValidationError):
        validate_ticker(raw)


def test_cash_must_be_finite_and_non_negative() -> None:
    assert validate_cash(0) == Decimal("0")
    assert validate_cash("100,000.50") == Decimal("100000.50")
    assert validate_cash("$25000") == Decimal("25000")
    with pytest.raises(PortfolioValidationError):
        validate_cash(-1)
    with pytest.raises(PortfolioValidationError):
        validate_cash(float("nan"))
    with pytest.raises(PortfolioValidationError):
        validate_cash(float("inf"))
    with pytest.raises(PortfolioValidationError):
        validate_cash("not-a-number")
    with pytest.raises(PortfolioValidationError):
        validate_cash(True)


def test_shares_must_be_positive_and_finite() -> None:
    assert validate_shares("10") == Decimal("10")
    assert validate_shares(Decimal("0.5")) == Decimal("0.5")
    with pytest.raises(PortfolioValidationError):
        validate_shares(-5)
    with pytest.raises(PortfolioValidationError):
        validate_shares(0)
    with pytest.raises(PortfolioValidationError):
        validate_shares(float("nan"))
    with pytest.raises(PortfolioValidationError):
        validate_shares(float("inf"))


def test_average_cost_must_be_positive() -> None:
    assert validate_average_cost("12.5") == Decimal("12.5")
    with pytest.raises(PortfolioValidationError):
        validate_average_cost(0)
    with pytest.raises(PortfolioValidationError):
        validate_average_cost(-3)
    with pytest.raises(PortfolioValidationError):
        validate_average_cost(float("nan"))


def test_position_batch_rejects_duplicates_and_normalizes() -> None:
    rows = [
        ("aapl", "10", "150"),
        ("MSFT", 5, None),
    ]
    validated = validate_positions(rows)
    assert validated == (
        ValidatedPosition("AAPL", Decimal("10"), Decimal("150")),
        ValidatedPosition("MSFT", Decimal("5"), None),
    )
    with pytest.raises(PortfolioValidationError, match="duplicate"):
        validate_positions([("AAPL", "1", None), ("aapl", "2", None)])


def test_position_batch_rejects_invalid_entries() -> None:
    with pytest.raises(PortfolioValidationError):
        validate_positions([("", "1", None)])
    with pytest.raises(PortfolioValidationError):
        validate_positions([("AAPL", "-1", None)])
    with pytest.raises(PortfolioValidationError):
        validate_positions([("AAPL", "nan", None)])


def test_validated_position_is_immutable_value() -> None:
    position = ValidatedPosition("AAPL", Decimal("1"), None)
    with pytest.raises(AttributeError):
        position.ticker = "MSFT"  # type: ignore[misc]
