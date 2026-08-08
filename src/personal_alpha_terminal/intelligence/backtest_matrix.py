from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from math import isfinite, sqrt

import numpy as np
import pandas as pd

from personal_alpha_terminal.intelligence.schemas import BacktestSafety, _aware


class IntelligenceVariant(StrEnum):
    QUANT_ONLY = "QUANT_ONLY"
    QUANT_EVENT = "QUANT_EVENT"
    QUANT_EVENT_PROBABILITY = "QUANT_EVENT_PROBABILITY"
    FULL_VALIDATED_INTELLIGENCE = "FULL_VALIDATED_INTELLIGENCE"


class SampleClassification(StrEnum):
    IN_SAMPLE = "IN_SAMPLE"
    VALIDATION = "VALIDATION"
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"


@dataclass(frozen=True, slots=True)
class BacktestVariantInput:
    variant: IntelligenceVariant
    gross_returns: pd.Series
    net_returns: pd.Series
    benchmark_returns: pd.Series
    turnover: pd.Series
    exposure: pd.Series
    sample_classification: SampleClassification
    data_version: str
    model_version: str
    transaction_cost_model_version: str
    backtest_safety: BacktestSafety


@dataclass(frozen=True, slots=True)
class IntelligenceBacktestMetrics:
    variant: IntelligenceVariant
    cagr: float
    alpha: float
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    maximum_drawdown: float
    annualized_volatility: float
    turnover: float
    win_rate: float
    profit_factor: float | None
    average_exposure: float
    gross_return: float
    transaction_cost_adjusted_return: float
    transaction_cost_drag: float
    observations: int
    sample_classification: SampleClassification
    data_version: str
    model_version: str
    backtest_safety: BacktestSafety


@dataclass(frozen=True, slots=True)
class IntelligenceBacktestMatrix:
    matrix_id: str
    results: tuple[IntelligenceBacktestMetrics, ...]
    data_cutoff: datetime
    comparison_status: str


class BacktestMatrixEvaluator:
    """Compares already executed PIT backtests; it does not manufacture strategies."""

    def evaluate(
        self,
        variants: tuple[BacktestVariantInput, ...],
        *,
        data_cutoff: datetime,
        periods_per_year: int = 252,
    ) -> IntelligenceBacktestMatrix:
        _aware(data_cutoff, "data_cutoff")
        if periods_per_year < 1:
            raise ValueError("periods_per_year must be positive")
        if len({item.variant for item in variants}) != len(variants):
            raise ValueError("backtest matrix variants must be unique")
        results = tuple(
            self._evaluate_variant(item, data_cutoff, periods_per_year)
            for item in sorted(variants, key=lambda item: item.variant.value)
        )
        status = (
            "OOS_COMPARABLE"
            if results
            and all(
                item.sample_classification is SampleClassification.OUT_OF_SAMPLE
                and item.backtest_safety is BacktestSafety.BACKTEST_SAFE
                for item in results
            )
            else "RESEARCH_ONLY"
        )
        fingerprint = "|".join(
            (
                data_cutoff.isoformat(),
                status,
                *(
                    f"{item.variant.value}:{item.data_version}:{item.model_version}:"
                    f"{item.transaction_cost_adjusted_return:.12f}"
                    for item in results
                ),
            )
        )
        return IntelligenceBacktestMatrix(
            sha256(fingerprint.encode()).hexdigest(),
            results,
            data_cutoff,
            status,
        )

    @staticmethod
    def _evaluate_variant(
        item: BacktestVariantInput,
        cutoff: datetime,
        periods_per_year: int,
    ) -> IntelligenceBacktestMetrics:
        frame = pd.concat(
            {
                "gross": item.gross_returns,
                "net": item.net_returns,
                "benchmark": item.benchmark_returns,
                "turnover": item.turnover,
                "exposure": item.exposure,
            },
            axis=1,
        ).dropna()
        if len(frame) < 30 or not isinstance(frame.index, pd.DatetimeIndex):
            raise ValueError("backtest matrix requires at least 30 aligned observations")
        if frame.index.tz is None or frame.index.max().to_pydatetime() > cutoff:
            raise ValueError("backtest matrix violates its PIT cutoff")
        if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
            raise ValueError("backtest matrix index must be sorted and unique")
        values = frame.to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("backtest matrix contains non-finite values")
        if bool((frame["turnover"] < 0).any()) or bool(
            ((frame["exposure"] < 0) | (frame["exposure"] > 1)).any()
        ):
            raise ValueError("turnover/exposure values are invalid")
        net = frame["net"]
        gross = frame["gross"]
        benchmark = frame["benchmark"]
        equity = (1 + net).cumprod()
        drawdown = equity / equity.cummax() - 1
        total_net = float(equity.iloc[-1] - 1)
        total_gross = float((1 + gross).prod() - 1)
        years = len(frame) / periods_per_year
        cagr = float(equity.iloc[-1] ** (1 / years) - 1)
        benchmark_cagr = float((1 + benchmark).prod() ** (1 / years) - 1)
        volatility = float(net.std(ddof=1) * sqrt(periods_per_year))
        std = float(net.std(ddof=1))
        sharpe = float(net.mean() / std * sqrt(periods_per_year)) if std > 0 else None
        downside = net[net < 0]
        downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
        sortino = (
            float(net.mean() / downside_std * sqrt(periods_per_year))
            if downside_std > 0
            else None
        )
        maximum_drawdown = float(drawdown.min())
        calmar = cagr / abs(maximum_drawdown) if maximum_drawdown < 0 else None
        gains = float(net[net > 0].sum())
        losses = float(-net[net < 0].sum())
        profit_factor = gains / losses if losses > 0 else None
        metrics = IntelligenceBacktestMetrics(
            variant=item.variant,
            cagr=cagr,
            alpha=cagr - benchmark_cagr,
            sharpe=sharpe,
            sortino=sortino,
            calmar=calmar,
            maximum_drawdown=maximum_drawdown,
            annualized_volatility=volatility,
            turnover=float(frame["turnover"].sum()),
            win_rate=float((net > 0).mean()),
            profit_factor=profit_factor,
            average_exposure=float(frame["exposure"].mean()),
            gross_return=total_gross,
            transaction_cost_adjusted_return=total_net,
            transaction_cost_drag=total_gross - total_net,
            observations=len(frame),
            sample_classification=item.sample_classification,
            data_version=item.data_version,
            model_version=item.model_version,
            backtest_safety=item.backtest_safety,
        )
        numeric = (
            metrics.cagr,
            metrics.alpha,
            metrics.maximum_drawdown,
            metrics.annualized_volatility,
            metrics.turnover,
            metrics.win_rate,
            metrics.average_exposure,
            metrics.gross_return,
            metrics.transaction_cost_adjusted_return,
            metrics.transaction_cost_drag,
        )
        if any(not isfinite(value) for value in numeric):
            raise ArithmeticError("backtest matrix produced non-finite metrics")
        return metrics
