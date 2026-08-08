from decimal import Decimal

from personal_alpha_terminal.data.market_data.schemas import PriceBar
from personal_alpha_terminal.data.market_data_quality.schemas import (
    AdjustmentMode,
    PriceUseCase,
)


class UnsafeAdjustmentError(ValueError):
    """Raised when a price adjustment is not safe for the requested use."""


ALLOWED_MODES: dict[PriceUseCase, frozenset[AdjustmentMode]] = {
    PriceUseCase.DISPLAY: frozenset({AdjustmentMode.RAW, AdjustmentMode.FORWARD}),
    PriceUseCase.VALUATION: frozenset({AdjustmentMode.RAW}),
    PriceUseCase.EXECUTION: frozenset({AdjustmentMode.RAW}),
    PriceUseCase.BACKTEST: frozenset({AdjustmentMode.POINT_IN_TIME_TOTAL_RETURN}),
    PriceUseCase.CROSS_SOURCE_VALIDATION: frozenset(
        {
            AdjustmentMode.RAW,
            AdjustmentMode.FORWARD,
            AdjustmentMode.BACKWARD,
            AdjustmentMode.PROVIDER_TOTAL_RETURN,
        }
    ),
}


def assert_adjustment_safe(use_case: PriceUseCase, mode: AdjustmentMode) -> None:
    if mode not in ALLOWED_MODES[use_case]:
        raise UnsafeAdjustmentError(
            f"{mode.value} is not safe for {use_case.value}; allowed modes are "
            f"{sorted(item.value for item in ALLOWED_MODES[use_case])}."
        )


def price_for_mode(bar: PriceBar, mode: AdjustmentMode) -> Decimal:
    if mode == AdjustmentMode.RAW:
        return bar.close
    if mode == AdjustmentMode.FORWARD:
        if bar.forward_adjusted_close is None:
            raise UnsafeAdjustmentError("Forward-adjusted close is unavailable.")
        return bar.forward_adjusted_close
    if mode == AdjustmentMode.BACKWARD:
        if bar.backward_adjusted_close is None:
            raise UnsafeAdjustmentError("Backward-adjusted close is unavailable.")
        return bar.backward_adjusted_close
    if mode == AdjustmentMode.PROVIDER_TOTAL_RETURN:
        if bar.adjusted_close is None:
            raise UnsafeAdjustmentError("Provider total-return close is unavailable.")
        return bar.adjusted_close
    raise UnsafeAdjustmentError(
        "Point-in-time total-return prices must be constructed from the corporate-action "
        "ledger and cannot be read from a current provider-adjusted history."
    )
