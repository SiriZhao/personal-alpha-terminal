"""Canonical backtest API with research backends loaded only on demand.

Daily, doctor and production-backtest imports must not pull optional VectorBT,
Backtrader, Numba or PyArrow stacks into the terminal runtime.  The VectorBT
names remain available for compatibility through :func:`__getattr__`.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

from personal_alpha_terminal.quant_engine.backtest.performance import (
    BacktestPerformance,
    evaluate_equity_curve,
)
from personal_alpha_terminal.quant_engine.backtest.production import (
    AccountingPoint,
    BacktestTarget,
    CorporateAction,
    CorporateActionType,
    ProductionBacktestConfig,
    ProductionBacktestDataset,
    ProductionBacktestEngine,
    ProductionBacktestMetrics,
    ProductionBacktestResult,
    ProductionTrade,
)
from personal_alpha_terminal.quant_engine.backtest.validation import (
    LockedParameters,
    RobustnessAssessment,
    RobustnessObservation,
    RobustnessScenario,
    TimeSeriesSplit,
    WalkForwardFold,
    assess_robustness,
    build_walk_forward_folds,
)

if TYPE_CHECKING:
    from personal_alpha_terminal.quant_engine.backtest.vectorbt_engine import (
        MAOptimizationResult,
        VectorBTConfig,
        VectorBTEngine,
        VectorBTResult,
    )

_OPTIONAL_VECTORBT_EXPORTS = frozenset(
    {"MAOptimizationResult", "VectorBTConfig", "VectorBTEngine", "VectorBTResult"}
)


def __getattr__(name: str) -> Any:
    if name not in _OPTIONAL_VECTORBT_EXPORTS:
        raise AttributeError(name)
    module = import_module("personal_alpha_terminal.quant_engine.backtest.vectorbt_engine")
    return getattr(module, name)

__all__ = [
    "AccountingPoint",
    "BacktestTarget",
    "BacktestPerformance",
    "CorporateAction",
    "CorporateActionType",
    "LockedParameters",
    "MAOptimizationResult",
    "ProductionBacktestConfig",
    "ProductionBacktestDataset",
    "ProductionBacktestEngine",
    "ProductionBacktestMetrics",
    "ProductionBacktestResult",
    "ProductionTrade",
    "RobustnessAssessment",
    "RobustnessObservation",
    "RobustnessScenario",
    "TimeSeriesSplit",
    "VectorBTConfig",
    "VectorBTEngine",
    "VectorBTResult",
    "WalkForwardFold",
    "assess_robustness",
    "build_walk_forward_folds",
    "evaluate_equity_curve",
]
