from dataclasses import dataclass, replace
from datetime import date
from typing import Protocol

from personal_alpha_terminal.backtest.engine import BacktestEngine
from personal_alpha_terminal.backtest.schemas import (
    BacktestConfig,
    BacktestDataset,
    BacktestResult,
)
from personal_alpha_terminal.backtest.strategy import BacktestStrategy


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date

    def __post_init__(self) -> None:
        if not (
            self.train_start <= self.train_end
            < self.validation_start
            <= self.validation_end
            < self.test_start
            <= self.test_end
        ):
            raise ValueError("walk-forward train/validation/test windows must not overlap")


class WalkForwardTrainer(Protocol):
    def fit(
        self,
        dataset: BacktestDataset,
        *,
        train_start: date,
        train_end: date,
        validation_start: date,
        validation_end: date,
    ) -> BacktestStrategy: ...


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    window: WalkForwardWindow
    frozen_parameters: dict[str, object]
    validation: BacktestResult
    test: BacktestResult


def run_walk_forward(
    dataset: BacktestDataset,
    base_config: BacktestConfig,
    windows: tuple[WalkForwardWindow, ...],
    trainer: WalkForwardTrainer,
    *,
    engine: BacktestEngine | None = None,
) -> tuple[WalkForwardResult, ...]:
    runner = engine or BacktestEngine()
    output: list[WalkForwardResult] = []
    previous_test_end: date | None = None
    for window in windows:
        if previous_test_end is not None and window.test_start <= previous_test_end:
            raise ValueError("walk-forward test windows must be strictly advancing")
        fit_dataset = _slice_dataset(
            dataset,
            start_date=window.train_start,
            end_date=window.validation_end,
        )
        strategy = trainer.fit(
            fit_dataset,
            train_start=window.train_start,
            train_end=window.train_end,
            validation_start=window.validation_start,
            validation_end=window.validation_end,
        )
        frozen = strategy.audit_payload()
        validation = runner.run(
            dataset,
            strategy,
            replace(
                base_config,
                start_date=window.validation_start,
                end_date=window.validation_end,
            ),
        )
        test = runner.run(
            dataset,
            strategy,
            replace(base_config, start_date=window.test_start, end_date=window.test_end),
        )
        if strategy.audit_payload() != frozen:
            raise RuntimeError("strategy parameters changed after the test set was locked")
        output.append(WalkForwardResult(window, frozen, validation, test))
        previous_test_end = window.test_end
    return tuple(output)


def _slice_dataset(
    dataset: BacktestDataset,
    *,
    start_date: date,
    end_date: date,
) -> BacktestDataset:
    """Create the only dataset visible to fitting; locked-test rows are absent."""

    return BacktestDataset(
        market=dataset.market,
        bars=tuple(
            item for item in dataset.bars if start_date <= item.trade_date <= end_date
        ),
        data_sources=dataset.data_sources,
        calendar=tuple(
            item for item in dataset.calendar if start_date <= item <= end_date
        ),
        calendar_source=dataset.calendar_source,
        universe_timeline=tuple(
            item for item in dataset.universe_timeline if item.as_of_date <= end_date
        ),
    )
