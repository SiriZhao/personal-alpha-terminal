"""Optional backtest adapters guarded by certified research-data authorization."""

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
from personal_alpha_terminal.quant_engine.backtest.vectorbt_engine import (
    MAOptimizationResult,
    VectorBTConfig,
    VectorBTEngine,
    VectorBTResult,
)

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
