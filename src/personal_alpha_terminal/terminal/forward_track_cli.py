"""CLI handlers for the immutable forward prediction/outcome ledger.

The ledger records what the system actually recommended (ForwardPrediction) and
appends later observed outcomes (ForwardOutcome) without ever simulating a fill
or mutating a prediction.  This is a historical evidence system, not paper
trading.
"""
from __future__ import annotations

from argparse import Namespace
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from personal_alpha_terminal.quant_engine.forward_track import (
    ForwardOutcome,
    append_outcome,
    load_forward_ledger,
)

console = Console()

OUTCOME_HORIZONS = (
    "1D",
    "5D",
    "10D",
    "H21",
    "SPY_REL",
    "QQQ_REL",
    "MAE",
    "MFE",
    "HORIZON",
)


def forward_track_command(args: Namespace) -> int:
    from personal_alpha_terminal.terminal.config import load_config

    config = load_config(args.config)
    path = config.forward_ledger_path
    action = getattr(args, "forward_track_action", "report")
    if action == "report":
        return _report(path)
    if action == "append-outcome":
        return _append_outcome(path, args)
    console.print(f"Unknown forward-track action: {action}")
    return 2


def _report(path: Path) -> int:
    predictions, outcomes = load_forward_ledger(path)
    console.print("[bold]FORWARD VALIDATION LEDGER[/bold]")
    console.print(f"Path: {path.resolve()}")
    console.print(f"Predictions: {len(predictions)}")
    console.print(f"Outcome records: {len(outcomes)}")
    if not predictions:
        console.print("No forward predictions recorded yet.")
        return 0
    table = Table(title="Prediction / Outcome Summary")
    table.add_column("Recommendation")
    table.add_column("Symbol")
    table.add_column("Run")
    table.add_column("Decision")
    table.add_column("Target")
    table.add_column("Alpha")
    table.add_column("Outcomes")
    for key, prediction in sorted(predictions.items()):
        keys = [outcome_key for outcome_key in outcomes if outcome_key.startswith(key + "::")]
        table.add_row(
            prediction.recommendation_id,
            prediction.symbol,
            prediction.run_id,
            prediction.decision_time.date().isoformat(),
            f"{prediction.target_weight:.4f}",
            f"{prediction.expected_alpha:+.4f}",
            str(len(keys)),
        )
    console.print(table)
    return 0


def _append_outcome(path: Path, args: Namespace) -> int:
    recommendation_id = str(args.recommendation_id)
    horizon = str(args.horizon)
    if horizon not in OUTCOME_HORIZONS:
        console.print(f"Invalid horizon {horizon!r}; choose from {', '.join(OUTCOME_HORIZONS)}")
        return 2
    outcome = ForwardOutcome(
        recommendation_id=recommendation_id,
        observed_at=datetime.fromisoformat(str(args.observed_at)),
        observed_price=float(args.observed_price),
        benchmark_price=float(args.benchmark_price),
        realized_return=float(args.realized_return),
        benchmark_return=float(args.benchmark_return),
        realized_benchmark_relative_return=float(args.relative_return),
        outcome_source=str(args.source),
        horizon=horizon,
        return_1d=_optional_float(args.return_1d),
        return_5d=_optional_float(args.return_5d),
        return_10d=_optional_float(args.return_10d),
        return_horizon=_optional_float(args.return_horizon),
        spy_relative_return=_optional_float(args.spy_relative),
        qqq_relative_return=_optional_float(args.qqq_relative),
        max_adverse_excursion=_optional_float(args.max_adverse_excursion),
        max_favorable_excursion=_optional_float(args.max_favorable_excursion),
    )
    append_outcome(outcome, path)
    console.print(
        f"Appended {outcome.horizon} outcome for {outcome.recommendation_id} "
        f"(realized {outcome.realized_return:+.4f}, "
        f"relative {outcome.realized_benchmark_relative_return:+.4f})"
    )
    return 0


def _optional_float(value: str | None) -> float | None:
    return float(value) if value is not None else None
